"""
bear_researcher.py -- SCOUT-BEAR two-phase researcher.

Phase 1: generate_queries(paper) -> list[str]
Phase 2: synthesize_brief(paper, search_results) -> str  (markdown brief)
"""
import argparse
import json
import re
import sys
import os
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prompts import BEAR_RESEARCHER_SYSTEM_PROMPT
from tools.llm import call_llm

AGENT_NAME = "BEAR_RESEARCHER"
MODEL = "qwen3:8b"


def _parse_queries(raw_output: str) -> list[str]:
    m = re.search(r"```json\s*(\{.*?\})\s*```", raw_output, re.DOTALL)
    if not m:
        m = re.search(r"(\{[^{}]*\"queries\"[^{}]*\})", raw_output, re.DOTALL)
    if m:
        data = json.loads(m.group(1))
        queries = data.get("queries", [])
        if isinstance(queries, list) and queries:
            return [str(q).strip() for q in queries if str(q).strip()]

    m = re.search(r"(\[\s*\".*?\"\s*\])", raw_output, re.DOTALL)
    if m:
        queries = json.loads(m.group(1))
        if isinstance(queries, list) and queries:
            return [str(q).strip() for q in queries if str(q).strip()]

    raise ValueError(f"Could not locate queries JSON in output:\n{raw_output[:500]}")


def generate_queries(paper: dict, logger=None) -> list[str]:
    def log(msg):
        if logger: logger(f"[{AGENT_NAME}] {msg}")

    log("Generating search queries...")
    user_msg = (
        "PHASE: QUERY_GENERATION\n\n"
        f"paper:\n```json\n{json.dumps(paper, indent=2)}\n```"
    )
    raw = call_llm(MODEL, BEAR_RESEARCHER_SYSTEM_PROMPT, user_msg, temperature=0.3)
    queries = _parse_queries(raw)
    log(f"Generated {len(queries)} queries")
    return queries


def synthesize_brief(paper: dict, search_results: dict, logger=None) -> str:
    def log(msg):
        if logger: logger(f"[{AGENT_NAME}] {msg}")

    log("Synthesizing research brief...")
    user_msg = (
        "PHASE: SYNTHESIS\n\n"
        f"paper:\n```json\n{json.dumps(paper, indent=2)}\n```\n\n"
        f"search_results:\n```json\n{json.dumps(search_results, indent=2)}\n```"
    )
    brief = call_llm(MODEL, BEAR_RESEARCHER_SYSTEM_PROMPT, user_msg, temperature=0.4)
    log(f"Brief length: {len(brief)} chars")
    return brief


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Run Bear Researcher standalone")
    ap.add_argument("--paper", default="sample_input.json", help="Path to paper JSON")
    ap.add_argument("--no-search", action="store_true", help="Skip DuckDuckGo search")
    ap.add_argument("--output-dir", default="outputs", help="Directory for output files")
    args = ap.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    paper_path = Path(args.paper) if Path(args.paper).is_absolute() else project_root / args.paper
    output_dir = Path(args.output_dir) if Path(args.output_dir).is_absolute() else project_root / args.output_dir
    output_dir.mkdir(exist_ok=True)

    paper = json.loads(paper_path.read_text())
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    def log(msg):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

    queries = generate_queries(paper, logger=log)
    (output_dir / f"{run_id}_bear_queries.json").write_text(json.dumps({"queries": queries}, indent=2))
    log(f"Queries saved to {run_id}_bear_queries.json")

    if args.no_search:
        log("--no-search: stubbing empty results")
        search_results = {q: [] for q in queries}
    else:
        from tools.search import batch_search
        log(f"Running {len(queries)} DuckDuckGo searches...")
        search_results = batch_search(queries, max_results=5)
        log(f"Retrieved {sum(len(v) for v in search_results.values())} hits")
    (output_dir / f"{run_id}_bear_search_raw.json").write_text(json.dumps(search_results, indent=2))

    brief = synthesize_brief(paper, search_results, logger=log)
    (output_dir / f"{run_id}_bear_brief.md").write_text(brief)
    log(f"Brief saved to {run_id}_bear_brief.md")
