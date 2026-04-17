"""
bull_analyst.py -- APEX. Consumes paper + Bull research brief, emits investment thesis.
"""
import argparse
import json
import sys
import os
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prompts import BULL_ANALYST_SYSTEM_PROMPT
from tools.llm import call_llm

AGENT_NAME = "BULL_ANALYST"
MODEL = "deepseek-r1:14b"


def run(paper: dict, research_brief: str, logger=None) -> str:
    def log(msg):
        if logger: logger(f"[{AGENT_NAME}] {msg}")

    log("Building prompt (paper + research brief)...")
    user_msg = (
        f"paper:\n```json\n{json.dumps(paper, indent=2)}\n```\n\n"
        f"research_brief:\n{research_brief}"
    )

    log(f"Sending to analyst model ({MODEL})...")
    output = call_llm(MODEL, BULL_ANALYST_SYSTEM_PROMPT, user_msg, temperature=0.4)
    log(f"Done. Output length: {len(output)} chars")
    return output


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Run Bull Analyst standalone")
    ap.add_argument("--paper", default="sample_input.json", help="Path to paper JSON")
    ap.add_argument("--brief", default=None, help="Path to bull brief markdown (defaults to latest in output-dir)")
    ap.add_argument("--output-dir", default="outputs", help="Directory for output files")
    args = ap.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    paper_path = Path(args.paper) if Path(args.paper).is_absolute() else project_root / args.paper
    output_dir = Path(args.output_dir) if Path(args.output_dir).is_absolute() else project_root / args.output_dir
    output_dir.mkdir(exist_ok=True)

    paper = json.loads(paper_path.read_text())

    if args.brief:
        brief_path = Path(args.brief) if Path(args.brief).is_absolute() else project_root / args.brief
        brief = brief_path.read_text()
    else:
        candidates = sorted(output_dir.glob("*_bull_brief.md"))
        if not candidates:
            print("ERROR: no bull brief found. Run bull_researcher.py first, or pass --brief.")
            sys.exit(1)
        brief = candidates[-1].read_text()
        print(f"Using brief: {candidates[-1].name}")

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    def log(msg):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

    thesis = run(paper, brief, logger=log)
    out_path = output_dir / f"{run_id}_bull_thesis.md"
    out_path.write_text(thesis)
    log(f"Thesis saved to {out_path.name}")
