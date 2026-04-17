"""
bull_analyst.py -- APEX. Consumes paper + Bull research brief, emits investment thesis.
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prompts import BULL_ANALYST_SYSTEM_PROMPT

AGENT_NAME = "BULL_ANALYST"


def run(pipe, paper: dict, research_brief: str, logger=None) -> str:
    def log(msg):
        if logger: logger(f"[{AGENT_NAME}] {msg}")

    log("Building prompt (paper + research brief)...")
    user_msg = (
        f"paper:\n```json\n{json.dumps(paper, indent=2)}\n```\n\n"
        f"research_brief:\n{research_brief}"
    )
    messages = [
        {"role": "system", "content": BULL_ANALYST_SYSTEM_PROMPT},
        {"role": "user",   "content": user_msg},
    ]

    log("Sending to analyst model (32B reasoning)...")
    result = pipe(
        messages,
        max_new_tokens=8192,
        temperature=0.4,
        do_sample=True,
    )
    output = result[0]["generated_text"][-1]["content"]
    log(f"Done. Output length: {len(output)} chars")
    return output
