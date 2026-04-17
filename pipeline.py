"""
pipeline.py -- 4-agent Bull/Bear pipeline with web research.

Runs fully locally via Ollama (Metal-accelerated, Q4 quantized).

USAGE:
    python pipeline.py                         # full 4-stage, both branches
    python pipeline.py --agent bull            # only bull branch
    python pipeline.py --agent bear            # only bear branch
    python pipeline.py --dry-run               # print prompts, no model calls
    python pipeline.py --no-search             # stub empty search results
    python pipeline.py --skip-research         # reuse last briefs, re-run analysts only
    python pipeline.py --input my_paper.json   # custom input file

FLOW per branch:
    paper -> Researcher(query_gen) -> DDG search -> Researcher(synthesis)
             -> Analyst(paper + brief) -> final thesis/critique

Models (Ollama, Metal, Q4):
    Researcher: qwen3:8b       (5.2 GB, already installed)
    Analyst:    deepseek-r1:14b (~8.5 GB, run: ollama pull deepseek-r1:14b)
"""
import sys
import os
import json
import argparse
import time
import traceback
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

from dotenv import load_dotenv
load_dotenv(PROJECT_DIR / ".env")

from agents import bull_researcher, bear_researcher, bull_analyst, bear_analyst
from agents.judge_agent import judge_agent
from tools.search import batch_search
from prompts import (
    BULL_RESEARCHER_SYSTEM_PROMPT, BEAR_RESEARCHER_SYSTEM_PROMPT,
    BULL_ANALYST_SYSTEM_PROMPT,    BEAR_ANALYST_SYSTEM_PROMPT,
)

# ── Output directory ──────────────────────────────────────────────────────────
OUTPUT_DIR = PROJECT_DIR / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

# ── Logging ───────────────────────────────────────────────────────────────────
def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)

# ── IO helpers ────────────────────────────────────────────────────────────────
def save_json(path: Path, obj):
    path.write_text(json.dumps(obj, indent=2))
    log(f"Saved: {path.name}")

def save_text(path: Path, text: str):
    path.write_text(text)
    log(f"Saved: {path.name}")

# ── Research phase (per branch) ───────────────────────────────────────────────
def run_research_branch(side: str, researcher_module, paper, run_id, no_search=False):
    """Phases 1-3 for a single side. Returns the brief markdown string."""
    try:
        queries = researcher_module.generate_queries(paper, logger=log)
        save_json(OUTPUT_DIR / f"{run_id}_{side}_queries.json", {"queries": queries})

        if no_search:
            log(f"[{side.upper()}] --no-search: stubbing empty results")
            search_results = {q: [] for q in queries}
        else:
            log(f"[{side.upper()}] Running {len(queries)} DuckDuckGo searches...")
            search_results = batch_search(queries, max_results=5)
            hit_count = sum(len(v) for v in search_results.values())
            log(f"[{side.upper()}] Retrieved {hit_count} total search hits")
        save_json(OUTPUT_DIR / f"{run_id}_{side}_search_raw.json", search_results)

        brief = researcher_module.synthesize_brief(paper, search_results, logger=log)
        save_text(OUTPUT_DIR / f"{run_id}_{side}_brief.md", brief)

        return side, brief, None
    except Exception:
        err = traceback.format_exc()
        log(f"ERROR in {side} research branch:\n{err}")
        return side, None, err

# ── Analysis phase (per branch) ───────────────────────────────────────────────
def run_analysis_branch(side: str, analyst_module, paper, brief, run_id):
    try:
        output = analyst_module.run(paper, brief, logger=log)
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
    args = ap.parse_args()

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

    # ── STAGE A: Research ─────────────────────────────────────────────────────
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
        with ThreadPoolExecutor(max_workers=1) as ex:
            futures = {
                ex.submit(run_research_branch, s, researcher_mods[s],
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

    # ── STAGE B: Analysis ─────────────────────────────────────────────────────
    active_sides = [s for s in sides if briefs.get(s) is not None]
    if not active_sides:
        log("ERROR: no briefs available for analysis. Aborting.")
        sys.exit(1)

    results = {}
    with ThreadPoolExecutor(max_workers=1) as ex:
        futures = {
            ex.submit(run_analysis_branch, s, analyst_mods[s],
                      paper, briefs[s], run_id): s
            for s in active_sides
        }
        for fut in as_completed(futures):
            side, output, err = fut.result()
            results[side] = {"output": output, "error": err}

    # ── STAGE C: Judge ────────────────────────────────────────────────────────
    bull_output = results.get("bull", {}).get("output")
    bear_output = results.get("bear", {}).get("output")

    if bull_output and bear_output:
        log("Running Judge Agent (2-pass evaluation + pitch deck)...")
        # Build evidence list from search results stored on disk
        bull_search_path = OUTPUT_DIR / f"{run_id}_bull_search_raw.json"
        bear_search_path = OUTPUT_DIR / f"{run_id}_bear_search_raw.json"
        evidence = []
        for path, label in [(bull_search_path, "bull"), (bear_search_path, "bear")]:
            if path.exists():
                try:
                    sr = json.loads(path.read_text())
                    for query, hits in sr.items():
                        for hit in hits[:2]:
                            evidence.append({
                                "question": query,
                                "tool": f"DuckDuckGo ({label})",
                                "result": f"{hit.get('title','')}: {hit.get('snippet','')}"
                            })
                except Exception:
                    pass

        state = {
            "title": paper.get("title", ""),
            "source_type": "research_paper",
            "abstract": paper.get("abstract", ""),
            "authors": paper.get("authors", []),
            "institution": paper.get("institution", ""),
            "bull_thesis": {"content": bull_output},
            "bear_thesis": {"content": bear_output},
            "evidence": evidence,
            "correction_guidance": "",
            "graph_context": "None available",
        }

        try:
            result_state = judge_agent(state)
            judge_eval = result_state.get("judge_evaluation", {})
            pitch_deck = result_state.get("pitch_deck", {})
            save_json(OUTPUT_DIR / f"{run_id}_judge_evaluation.json", judge_eval)
            save_json(OUTPUT_DIR / f"{run_id}_pitch_deck.json", pitch_deck)
            log(f"Judge complete — Score: {judge_eval.get('investability_score','?')}/100 "
                f"| Rec: {judge_eval.get('recommendation','?')}")
        except Exception:
            err = traceback.format_exc()
            log(f"Judge Agent FAILED:\n{err}")

    # ── Summary ───────────────────────────────────────────────────────────────
    for side, r in results.items():
        banner = f"{'='*70}\n{side.upper()} ANALYST OUTPUT\n{'='*70}"
        print(f"\n{banner}")
        print(r["error"] if r["error"] else r["output"])

    log(f"Pipeline complete. Run ID: {run_id}")
    log(f"Artifacts in: {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
