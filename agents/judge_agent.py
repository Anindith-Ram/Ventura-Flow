"""
Judge Agent — Senior VC Partner evaluation and investment memo generation.

This agent replaces the simple judge_node. It receives the bull and bear theses,
the raw research evidence, and the signal metadata, then produces a comprehensive
investment evaluation with reasoned (non-formulaic) scoring across multiple
dimensions, culminating in an Investability Score and a full pitch-deck-style memo
that a VC partner can act on in minutes.

Scores are NOT computed from formulas. Every number is the LLM's reasoned judgment
based solely on the arguments and evidence the bull/bear agents surfaced.
"""

import json
import logging
from datetime import datetime

from graph.state import AgentState
from tools.llm import call_llm

logger = logging.getLogger(__name__)
JUDGE_MODEL = "llama3.1:8b"

# ---------------------------------------------------------------------------
# System prompts — multi-pass evaluation
# ---------------------------------------------------------------------------

INVESTABILITY_SYSTEM = """\
You are a senior managing partner at a top-tier venture capital firm. You have
25 years of experience evaluating deep-tech, biotech, and software investments.
You are now the final decision-maker in a structured due-diligence pipeline.

You have received:
  1. A BULL thesis — an aggressive case FOR investing.
  2. A BEAR thesis — a skeptical case AGAINST investing.
  3. Raw research EVIDENCE collected by analyst tools.
  4. Signal metadata (source, authors, institution).

YOUR JOB: Produce a rigorous, reasoned investment evaluation. You are writing
for a partner meeting — every claim must trace back to evidence or be explicitly
flagged as an inference.

CRITICAL RULES:
- Do NOT use formulas, weighted averages, or mechanical scoring. Every score
  is your REASONED JUDGMENT after weighing the arguments.
- When bull and bear disagree, explain WHO you believe and WHY based on the
  evidence quality, not just the argument strength.
- Treat missing evidence the same way a real VC would: it's a yellow flag,
  not an automatic zero.
- Be specific. "Strong team" is useless. "Lead author has h-index 45, 3 prior
  exits, and a Nature paper in this exact domain" is useful.

Return ONLY valid JSON with this structure:

{
  "investability_score": <int 0-100>,
  "investability_rationale": "<3-5 sentences: why this exact number, what
    moved it up, what held it back>",

  "commercial_viability": <int 0-100>,
  "commercial_viability_rationale": "<Is there a path from this research/product
    to revenue? How clear is the market? How defensible?>",

  "team_signal_strength": <int 0-100>,
  "team_signal_rationale": "<Based on author track record, institutional
    affiliation, prior exits, h-index, industry ties — what do we actually
    know about execution capability?>",

  "timing_and_market": <int 0-100>,
  "timing_rationale": "<Is the market ready? Too early? Too late? Is there
    a catalyst or inflection point?>",

  "competitive_moat": <int 0-100>,
  "moat_rationale": "<IP protection, data advantages, network effects,
    switching costs — what defensibility exists or is plausible?>",

  "risk_adjusted_conviction": <int 0-100>,
  "risk_conviction_rationale": "<After accounting for the bear's strongest
    points, how convicted are you? What is the risk/reward asymmetry?>",

  "recommendation": "STRONG_FLAG | FLAG | WATCH_LIST | PASS",

  "one_line_verdict": "<One sentence a GP can read in 5 seconds>",

  "evidence_quality_assessment": "<How good was the evidence the analysts
    collected? What's missing that a real diligence process would want?>",

  "bull_vs_bear_adjudication": {
    "bull_prevailed_on": ["<specific point and why>"],
    "bear_prevailed_on": ["<specific point and why>"],
    "unresolved_tensions": ["<points where neither side had enough evidence>"]
  }
}
"""

PITCH_DECK_SYSTEM = """\
You are a VC associate preparing an internal investment memo for the Monday
partner meeting. You have the full evaluation from the senior partner.
Your job is to turn this into a structured, scannable pitch deck summary
that partners can read in 3-4 minutes and decide whether to take a meeting.

Write this as a NARRATIVE, not a data dump. Partners hate bullet-point soup.
Each section should read like a paragraph a smart person wrote, not a template
that got filled in.

Return ONLY valid JSON:

{
  "memo_title": "<Signal name — one-line hook>",
  "memo_date": "<today's date>",
  "executive_summary": "<2-3 sentences. What is this, why should we care,
    what's our conviction level. This is the only section some partners will read.>",

  "the_opportunity": "<3-4 sentences. What problem does this solve, how big
    is the market, why now. Ground this in the evidence, not hype.>",

  "technology_differentiation": "<2-3 sentences on what makes the underlying
    tech/research novel. What can this do that alternatives cannot?>",

  "team_assessment": "<2-3 sentences. What do we know about the people behind
    this? Institutional credibility, track record, domain expertise. Be honest
    about gaps.>",

  "market_landscape": "<2-3 sentences. Who else is working on this? Where does
    this sit in the competitive map? Is this a crowded space or white space?>",

  "bull_case_narrative": "<3-4 sentences. The best version of the future where
    this works. Be specific about the path: what happens first, then what,
    then what outcome.>",

  "bear_case_narrative": "<3-4 sentences. The realistic failure modes. Not
    strawman risks but genuine concerns a skeptical partner would raise.>",

  "key_risks_ranked": [
    {"risk": "<specific risk>", "severity": "HIGH|MEDIUM|LOW",
     "mitigatable": true/false, "mitigation_path": "<if mitigatable, how>"}
  ],

  "what_we_need_to_believe": ["<The 2-3 core assumptions that must hold for
    this to be a good investment. Be precise.>"],

  "suggested_next_steps": ["<Concrete actions: who to call, what to research,
    what milestone to wait for>"],

  "comparable_transactions": "<Any relevant exits, funding rounds, or public
    comps the evidence surfaced. If none, say so explicitly.>",

  "partner_meeting_recommendation": "<TAKE_MEETING | MONITOR | PASS —
    and one sentence on why>"
}
"""

JSON_REPAIR_SYSTEM = """\
You repair malformed model outputs into valid JSON.

Rules:
- Return ONLY valid JSON.
- Do not add markdown fences or commentary.
- Preserve the original meaning as closely as possible.
- If a required field is missing, infer the best concise value from the source text.
""".strip()

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _parse_json(response: str) -> dict:
    """Extract JSON from LLM response, tolerating preamble/postamble text."""
    try:
        start = response.find("{")
        end = response.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(response[start:end])
    except json.JSONDecodeError:
        pass
    return {"error": "JSON parse failure", "raw": response[:800]}


def _is_valid_evaluation(data: dict) -> bool:
    required = [
        "investability_score",
        "investability_rationale",
        "commercial_viability",
        "commercial_viability_rationale",
        "team_signal_strength",
        "team_signal_rationale",
        "timing_and_market",
        "timing_rationale",
        "competitive_moat",
        "moat_rationale",
        "risk_adjusted_conviction",
        "risk_conviction_rationale",
        "recommendation",
        "one_line_verdict",
        "evidence_quality_assessment",
        "bull_vs_bear_adjudication",
    ]
    return all(k in data for k in required) and isinstance(
        data.get("bull_vs_bear_adjudication"), dict
    )


def _is_valid_pitch_deck(data: dict) -> bool:
    required = [
        "memo_title",
        "executive_summary",
        "the_opportunity",
        "technology_differentiation",
        "team_assessment",
        "market_landscape",
        "bull_case_narrative",
        "bear_case_narrative",
        "key_risks_ranked",
        "what_we_need_to_believe",
        "suggested_next_steps",
        "comparable_transactions",
        "partner_meeting_recommendation",
    ]
    return all(k in data for k in required)


def _coerce_evaluation(data: dict) -> dict:
    adjudication = data.get("bull_vs_bear_adjudication")
    if not isinstance(adjudication, dict):
        adjudication = {}
    data["bull_vs_bear_adjudication"] = {
        "bull_prevailed_on": adjudication.get("bull_prevailed_on", []),
        "bear_prevailed_on": adjudication.get("bear_prevailed_on", []),
        "unresolved_tensions": adjudication.get("unresolved_tensions", []),
    }
    return data


def _repair_json(raw_response: str, schema_name: str) -> dict:
    repair_prompt = (
        f"The following model output was supposed to be valid JSON for the schema "
        f"'{schema_name}' but was malformed.\n\n"
        f"Malformed output:\n{raw_response}\n"
    )
    repaired = call_llm(JUDGE_MODEL, JSON_REPAIR_SYSTEM, repair_prompt, temperature=0.0)
    return _parse_json(repaired)


def _call_structured_json(
    system_prompt: str,
    user_prompt: str,
    validator,
    schema_name: str,
) -> dict:
    raw_response = call_llm(JUDGE_MODEL, system_prompt, user_prompt)
    parsed = _parse_json(raw_response)
    if validator(parsed):
        return parsed

    logger.warning("[Judge Agent] %s output malformed; attempting JSON repair", schema_name)
    repaired = _repair_json(raw_response, schema_name)
    if validator(repaired):
        return repaired

    logger.warning("[Judge Agent] %s JSON repair failed; retrying original prompt once", schema_name)
    retry_response = call_llm(JUDGE_MODEL, system_prompt, user_prompt, temperature=0.0)
    retry_parsed = _parse_json(retry_response)
    if validator(retry_parsed):
        return retry_parsed

    repaired_retry = _repair_json(retry_response, schema_name)
    if validator(repaired_retry):
        return repaired_retry

    return retry_parsed


def _format_evidence_for_judge(evidence: list[dict]) -> str:
    """Format evidence with enough detail for the judge to trace claims."""
    if not evidence:
        return "NO EVIDENCE WAS COLLECTED. This is a significant limitation."
    parts = []
    for i, e in enumerate(evidence, 1):
        parts.append(
            f"── Evidence #{i} ──\n"
            f"Research question: {e.get('question', 'N/A')}\n"
            f"Tool used: {e.get('tool', 'N/A')}\n"
            f"Result:\n{e.get('result', 'No result')[:600]}"
        )
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Main judge agent node
# ---------------------------------------------------------------------------

def judge_agent(state: AgentState) -> AgentState:
    """
    Two-pass judge agent:
      Pass 1 — Investability evaluation: reasoned scoring across 6 dimensions.
      Pass 2 — Pitch deck memo: narrative synthesis for partner consumption.

    Replaces the old judge_node. Writes to state['scout_report'] (for pipeline
    compatibility) and state['pitch_deck'] (the new rich output).
    """

    title = state.get("title", "")
    source_type = state.get("source_type", "")
    abstract = state.get("abstract", "")
    authors = ", ".join(state.get("authors", []))
    institution = state.get("institution", "")
    bull = state.get("bull_thesis", {})
    bear = state.get("bear_thesis", {})
    evidence = state.get("evidence", [])
    correction = state.get("correction_guidance", "")

    evidence_text = _format_evidence_for_judge(evidence)

    # ── Pass 1: Investability evaluation ──────────────────────────────────
    system_1 = INVESTABILITY_SYSTEM
    if correction:
        system_1 += (
            f"\n\nIMPORTANT — CORRECTION FROM PRIOR VERIFICATION FAILURE:\n"
            f"{correction}\n"
            "Adjust your evaluation to avoid the specific errors flagged above."
        )

    user_prompt_1 = (
        f"═══ SIGNAL UNDER EVALUATION ═══\n"
        f"Title: {title}\n"
        f"Source type: {source_type}\n"
        f"Authors: {authors}\n"
        f"Institution: {institution}\n"
        f"Abstract:\n{abstract[:600]}\n\n"
        f"═══ BULL THESIS (argues FOR investment) ═══\n"
        f"{json.dumps(bull, indent=2)}\n\n"
        f"═══ BEAR THESIS (argues AGAINST investment) ═══\n"
        f"{json.dumps(bear, indent=2)}\n\n"
        f"═══ RAW RESEARCH EVIDENCE ═══\n"
        f"{evidence_text}\n\n"
        f"═══ PRIOR SIGNALS CONTEXT ═══\n"
        f"{state.get('graph_context', 'None available')}\n\n"
        "Now produce your reasoned investment evaluation. Remember: every score "
        "is your judgment, not a formula. Trace claims to evidence."
    )

    evaluation = _call_structured_json(
        system_1,
        user_prompt_1,
        _is_valid_evaluation,
        "judge_evaluation",
    )
    evaluation = _coerce_evaluation(evaluation)

    # Clamp and validate the investability score
    inv_score = evaluation.get("investability_score", 50)
    if isinstance(inv_score, str):
        try:
            inv_score = int(inv_score)
        except ValueError:
            inv_score = 50
    inv_score = max(0, min(100, inv_score))
    evaluation["investability_score"] = inv_score

    # Validate recommendation
    valid_recs = {"STRONG_FLAG", "FLAG", "WATCH_LIST", "PASS"}
    if evaluation.get("recommendation") not in valid_recs:
        if inv_score >= 75:
            evaluation["recommendation"] = "STRONG_FLAG"
        elif inv_score >= 60:
            evaluation["recommendation"] = "FLAG"
        elif inv_score >= 35:
            evaluation["recommendation"] = "WATCH_LIST"
        else:
            evaluation["recommendation"] = "PASS"

    logger.info(
        f"[Judge Agent] Pass 1 complete — Investability: {inv_score}/100, "
        f"Rec: {evaluation.get('recommendation')}"
    )

    # ── Pass 2: Pitch deck memo ───────────────────────────────────────────
    user_prompt_2 = (
        f"═══ SIGNAL ═══\n"
        f"Title: {title}\n"
        f"Source: {source_type} | Authors: {authors} | Institution: {institution}\n"
        f"Abstract: {abstract[:400]}\n\n"
        f"═══ SENIOR PARTNER EVALUATION ═══\n"
        f"{json.dumps(evaluation, indent=2)}\n\n"
        f"═══ BULL THESIS ═══\n"
        f"{json.dumps(bull, indent=2)}\n\n"
        f"═══ BEAR THESIS ═══\n"
        f"{json.dumps(bear, indent=2)}\n\n"
        "Now write the internal investment memo. Be narrative, not bullet-point "
        "soup. Partners will spend 3-4 minutes on this. Make it count."
    )

    pitch_deck = _call_structured_json(
        PITCH_DECK_SYSTEM,
        user_prompt_2,
        _is_valid_pitch_deck,
        "pitch_deck",
    )
    pitch_deck["memo_date"] = datetime.utcnow().strftime("%Y-%m-%d")

    logger.info(
        f"[Judge Agent] Pass 2 complete — Memo: "
        f"{pitch_deck.get('memo_title', 'untitled')[:60]}"
    )

    # ── Write to state ────────────────────────────────────────────────────
    # scout_report for backward compatibility with verify/save/dashboard
    adjudication = evaluation.get("bull_vs_bear_adjudication", {})
    state["scout_report"] = {
        "score": inv_score,
        "recommendation": evaluation.get("recommendation", "WATCH_LIST"),
        "summary": evaluation.get("one_line_verdict", ""),
        "why_interesting": evaluation.get("investability_rationale", ""),
        "key_strengths": [
            f"Commercial viability ({evaluation.get('commercial_viability', '?')}/100): "
            f"{evaluation.get('commercial_viability_rationale', '')}",
            f"Team signal ({evaluation.get('team_signal_strength', '?')}/100): "
            f"{evaluation.get('team_signal_rationale', '')}",
            f"Competitive moat ({evaluation.get('competitive_moat', '?')}/100): "
            f"{evaluation.get('moat_rationale', '')}",
        ],
        "key_risks": [
            f"Timing/market ({evaluation.get('timing_and_market', '?')}/100): "
            f"{evaluation.get('timing_rationale', '')}",
            f"Risk-adjusted conviction ({evaluation.get('risk_adjusted_conviction', '?')}/100): "
            f"{evaluation.get('risk_conviction_rationale', '')}",
        ],
        "suggested_next_steps": pitch_deck.get("suggested_next_steps", []),
        "bull_won_on": adjudication.get("bull_prevailed_on", []),
        "bear_won_on": adjudication.get("bear_prevailed_on", []),
    }

    # The rich new outputs
    state["judge_evaluation"] = evaluation
    state["pitch_deck"] = pitch_deck

    return state
