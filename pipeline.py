"""
pipeline.py -- 4-agent Bull/Bear pipeline with web research.

USAGE:
    python pipeline.py                         # full 4-stage, both branches
    python pipeline.py --agent bull            # only bull branch
    python pipeline.py --agent bear            # only bear branch
    python pipeline.py --dry-run               # print prompts, no model calls
    python pipeline.py --no-search             # stub empty search results
    python pipeline.py --skip-research         # reuse last briefs, re-run analysts only
    python pipeline.py --input my_paper.json   # custom input file
    python pipeline.py --researcher-model Qwen/Qwen2.5-14B-Instruct
    python pipeline.py --analyst-model    some-other-model

FLOW per branch:
    paper -> Researcher(query_gen) -> DDG search -> Researcher(synthesis)
             -> Analyst(paper + brief) -> final thesis/critique

Researcher (Qwen2.5-7B) and Analyst (DeepSeek-R1-32B) models are loaded SEQUENTIALLY
to keep VRAM usage safe on a 40GB A100. The two branches run in parallel within each
model-loaded phase.
"""
import sys, os, json, argparse, time, traceback, gc
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))
os.environ.setdefault("HF_HOME", "/content/drive/MyDrive/Ventura-Flow/hf_cache")

from dotenv import load_dotenv
load_dotenv(PROJECT_DIR / ".env")
_hf_token = os.environ.get("HF_TOKEN")
if _hf_token:
    from huggingface_hub import login
    login(token=_hf_token, add_to_git_credential=False)
    log("Logged in to Hugging Face via .env")
else:
    log("WARNING: HF_TOKEN not found in .env — gated models may fail")

from agents import bull_researcher, bear_researcher, bull_analyst, bear_analyst
from tools.search import batch_search
from prompts import (
    BULL_RESEARCHER_SYSTEM_PROMPT, BEAR_RESEARCHER_SYSTEM_PROMPT,
    BULL_ANALYST_SYSTEM_PROMPT,    BEAR_ANALYST_SYSTEM_PROMPT,
)

# ── Defaults ──────────────────────────────────────────────────────────────────
RESEARCHER_MODEL = "Qwen/Qwen2.5-7B-Instruct"
ANALYST_MODEL    = "deepseek-ai/DeepSeek-R1-Distill-Qwen-32B"
OUTPUT_DIR       = PROJECT_DIR / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

# ── Logging ───────────────────────────────────────────────────────────────────
def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

# ── Model lifecycle ───────────────────────────────────────────────────────────
def _is_cached(model_id: str) -> bool:
    """Check if model weights exist in HF_HOME cache."""
    from huggingface_hub import try_to_load_from_cache, scan_cache_dir
    try:
        info = scan_cache_dir()
        cached_ids = {r.repo_id for r in info.repos}
        return model_id in cached_ids
    except Exception:
        return False


def load_pipeline(model_id: str, force_gpu: bool = False):
    import torch
    from transformers import pipeline

    cached = _is_cached(model_id)
    log(f"Loading model: {model_id} ({'from cache' if cached else 'DOWNLOADING -- this may take a while'})")
    vram = torch.cuda.get_device_properties(0).total_memory / 1e9
    log(f"VRAM available: {vram:.1f} GB")
    t0 = time.time()

    # Clear any lingering allocations from prior runs
    import gc
    gc.collect()
    torch.cuda.empty_cache()
    free_gb = torch.cuda.mem_get_info()[0] / 1e9
    log(f"Free VRAM before load: {free_gb:.1f} GB")

    if force_gpu:
        if free_gb < 12:
            log("WARNING: Low VRAM for force_gpu — falling back to device_map='auto'")
            force_gpu = False

    if force_gpu:
        # device=0 bypasses accelerate entirely — no CPU offloading, no meta tensors.
        pipe = pipeline(
            "text-generation",
            model=model_id,
            torch_dtype=torch.float16,
            device=0,
        )
    else:
        # Large models or low-VRAM fallback — accelerate shards across available memory.
        pipe = pipeline(
            "text-generation",
            model=model_id,
            torch_dtype=torch.float16,
            device_map="auto",
        )

    log(f"Model loaded in {time.time() - t0:.1f}s")
    return pipe


def unload_pipeline(pipe):
    import torch
    log("Unloading model and freeing VRAM...")
    del pipe
    gc.collect()
    torch.cuda.empty_cache()

# ── IO helpers ────────────────────────────────────────────────────────────────
def save_json(path: Path, obj):
    path.write_text(json.dumps(obj, indent=2))
    log(f"Saved: {path.name}")

def save_text(path: Path, text: str):
    path.write_text(text)
    log(f"Saved: {path.name}")

# ── Research phase (per branch) ───────────────────────────────────────────────
def run_research_branch(side: str, researcher_module, pipe, paper, run_id, no_search=False):
    """Phases 1-3 for a single side. Returns the brief markdown string."""
    try:
        # Phase 1: query generation
        queries = researcher_module.generate_queries(pipe, paper, logger=log)
        save_json(OUTPUT_DIR / f"{run_id}_{side}_queries.json", {"queries": queries})

        # Phase 2: DDG search
        if no_search:
            log(f"[{side.upper()}] --no-search: stubbing empty results")
            search_results = {q: [] for q in queries}
        else:
            log(f"[{side.upper()}] Running {len(queries)} DuckDuckGo searches...")
            search_results = batch_search(queries, max_results=5)
            hit_count = sum(len(v) for v in search_results.values())
            log(f"[{side.upper()}] Retrieved {hit_count} total search hits")
        save_json(OUTPUT_DIR / f"{run_id}_{side}_search_raw.json", search_results)

        # Phase 3: synthesize brief
        brief = researcher_module.synthesize_brief(pipe, paper, search_results, logger=log)
        save_text(OUTPUT_DIR / f"{run_id}_{side}_brief.md", brief)

        return side, brief, None
    except Exception:
        err = traceback.format_exc()
        log(f"ERROR in {side} research branch:\n{err}")
        return side, None, err

# ── Analysis phase (per branch) ───────────────────────────────────────────────
def run_analysis_branch(side: str, analyst_module, pipe, paper, brief, run_id):
    try:
        output = analyst_module.run(pipe, paper, brief, logger=log)
        ext = "thesis" if side == "bull" else "critique"
        save_text(OUTPUT_DIR / f"{run_id}_{side}_{ext}.md", output)
        return side, output, None
    except Exception:
        err = traceback.format_exc()
        log(f"ERROR in {side} analysis branch:\n{err}")
        return side, None, err

# ── Dry run ───────────────────────────────────────────────────────────────────
def dry_run(paper, sides):
    prompts = {
        "bull_researcher": BULL_RESEARCHER_SYSTEM_PROMPT,
        "bear_researcher": BEAR_RESEARCHER_SYSTEM_PROMPT,
        "bull_analyst":    BULL_ANALYST_SYSTEM_PROMPT,
        "bear_analyst":    BEAR_ANALYST_SYSTEM_PROMPT,
    }
    keys = []
    if "bull" in sides: keys += ["bull_researcher", "bull_analyst"]
    if "bear" in sides: keys += ["bear_researcher", "bear_analyst"]
    for k in keys:
        print(f"\n{'='*70}\n[DRY RUN] {k.upper()} SYSTEM PROMPT\n{'='*70}")
        print(prompts[k])
    print(f"\n[DRY RUN] PAPER INPUT:\n{json.dumps(paper, indent=2)[:800]}...")

# ── Latest-brief finder for --skip-research ───────────────────────────────────
def find_latest_brief(side: str) -> tuple[str, str] | None:
    """Return (run_id, brief_text) for most recent {side}_brief.md, or None."""
    candidates = sorted(OUTPUT_DIR.glob(f"*_{side}_brief.md"))
    if not candidates:
        return None
    latest = candidates[-1]
    run_id = latest.name.split(f"_{side}_brief.md")[0]
    return run_id, latest.read_text()

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent",  choices=["bull", "bear", "both"], default="both")
    ap.add_argument("--input",  default="sample_input.json")
    ap.add_argument("--dry-run",         action="store_true")
    ap.add_argument("--no-search",       action="store_true")
    ap.add_argument("--skip-research",   action="store_true")
    ap.add_argument("--researcher-model", default=RESEARCHER_MODEL)
    ap.add_argument("--analyst-model",    default=ANALYST_MODEL)
    args = ap.parse_args()

    # Load input
    input_path = PROJECT_DIR / args.input
    if not input_path.exists():
        log(f"ERROR: Input file not found: {input_path}")
        sys.exit(1)
    paper = json.loads(input_path.read_text())
    log(f"Loaded: {args.input} -- '{paper.get('title', 'unknown')[:70]}'")

    sides = ["bull", "bear"] if args.agent == "both" else [args.agent]

    if args.dry_run:
        dry_run(paper, sides)
        return

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    log(f"Run ID: {run_id}")

    researcher_mods = {"bull": bull_researcher, "bear": bear_researcher}
    analyst_mods    = {"bull": bull_analyst,    "bear": bear_analyst}
    briefs = {}

    # ── STAGE A: Research (unless skipping) ───────────────────────────────────
    if args.skip_research:
        log("--skip-research: loading latest briefs from disk")
        for side in sides:
            found = find_latest_brief(side)
            if found is None:
                log(f"ERROR: no prior brief found for {side}. Run without --skip-research first.")
                sys.exit(1)
            prev_run_id, brief = found
            briefs[side] = brief
            log(f"Loaded {side} brief from run {prev_run_id}")
    else:
        # force_gpu=True: 7B fits on A100, avoids CPU offloading + meta-device threading errors
        r_pipe = load_pipeline(args.researcher_model, force_gpu=True)
        # max_workers=1: GPU serializes calls anyway; concurrent calls on same pipe
        # corrupt accelerate's device hooks causing RuntimeError on meta device.
        with ThreadPoolExecutor(max_workers=1) as ex:
            futures = {
                ex.submit(run_research_branch, s, researcher_mods[s], r_pipe,
                          paper, run_id, args.no_search): s
                for s in sides
            }
            for fut in as_completed(futures):
                side, brief, err = fut.result()
                if err:
                    log(f"[{side.upper()}] research FAILED -- branch skipped")
                    briefs[side] = None
                else:
                    briefs[side] = brief
        unload_pipeline(r_pipe)

    # ── STAGE B: Analysis ─────────────────────────────────────────────────────
    active_sides = [s for s in sides if briefs.get(s) is not None]
    if not active_sides:
        log("ERROR: no briefs available for analysis. Aborting.")
        sys.exit(1)

    a_pipe = load_pipeline(args.analyst_model, force_gpu=False)  # 32B needs auto for CPU offload headroom
    results = {}
    with ThreadPoolExecutor(max_workers=1) as ex:  # same pipe concurrency fix
        futures = {
            ex.submit(run_analysis_branch, s, analyst_mods[s], a_pipe,
                      paper, briefs[s], run_id): s
            for s in active_sides
        }
        for fut in as_completed(futures):
            side, output, err = fut.result()
            results[side] = {"output": output, "error": err}
    unload_pipeline(a_pipe)

    # ── Summary ───────────────────────────────────────────────────────────────
    for side, r in results.items():
        banner = f"{'='*70}\n{side.upper()} ANALYST OUTPUT\n{'='*70}"
        print(f"\n{banner}")
        print(r["error"] if r["error"] else r["output"])

    log(f"Pipeline complete. Run ID: {run_id}")
    log(f"Artifacts in: {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
