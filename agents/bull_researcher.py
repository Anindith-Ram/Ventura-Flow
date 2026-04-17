"""
bull_researcher.py -- SCOUT-BULL two-phase researcher.

Phase 1: generate_queries(pipe, paper) -> list[str]
Phase 2: synthesize_brief(pipe, paper, search_results) -> str  (markdown brief)
"""
import sys, os, json, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prompts import BULL_RESEARCHER_SYSTEM_PROMPT

AGENT_NAME = "BULL_RESEARCHER"


def _parse_queries(raw_output: str) -> list[str]:
    """Extract the JSON query list from the model's output. Robust to stray text."""
    # Try fenced json block first
    m = re.search(r"```json\s*(\{.*?\})\s*```", raw_output, re.DOTALL)
    if not m:
        # Fallback: any {...} containing "queries"
        m = re.search(r"(\{[^{}]*\"queries\"[^{}]*\})", raw_output, re.DOTALL)
    if not m:
        raise ValueError(f"Could not locate queries JSON in output:\n{raw_output[:500]}")

    data = json.loads(m.group(1))
    queries = data.get("queries", [])
    if not isinstance(queries, list) or not queries:
        raise ValueError(f"Invalid queries field: {data}")
    return [str(q).strip() for q in queries if str(q).strip()]


def generate_queries(pipe, paper: dict, logger=None) -> list[str]:
    def log(msg):
        if logger: logger(f"[{AGENT_NAME}] {msg}")

    log("Generating search queries...")
    user_msg = (
        "PHASE: QUERY_GENERATION\n\n"
        f"paper:\n```json\n{json.dumps(paper, indent=2)}\n```"
    )
    messages = [
        {"role": "system", "content": BULL_RESEARCHER_SYSTEM_PROMPT},
        {"role": "user",   "content": user_msg},
    ]
    result = pipe(messages, max_new_tokens=512, temperature=0.3, do_sample=True)
    raw = result[0]["generated_text"][-1]["content"]
    queries = _parse_queries(raw)
    log(f"Generated {len(queries)} queries")
    return queries


def synthesize_brief(pipe, paper: dict, search_results: dict, logger=None) -> str:
    def log(msg):
        if logger: logger(f"[{AGENT_NAME}] {msg}")

    log("Synthesizing research brief...")
    user_msg = (
        "PHASE: SYNTHESIS\n\n"
        f"paper:\n```json\n{json.dumps(paper, indent=2)}\n```\n\n"
        f"search_results:\n```json\n{json.dumps(search_results, indent=2)}\n```"
    )
    messages = [
        {"role": "system", "content": BULL_RESEARCHER_SYSTEM_PROMPT},
        {"role": "user",   "content": user_msg},
    ]
    result = pipe(messages, max_new_tokens=3000, temperature=0.4, do_sample=True)
    brief = result[0]["generated_text"][-1]["content"]
    log(f"Brief length: {len(brief)} chars")
    return brief
