"""investor_signal_mcp — LLM-assisted novelty/IP/value paper scoring.

⚠️  NOT INVESTMENT ADVICE. Scores reflect transparent feature patterns only.

Tools
-----
score_investor_relevance    Score one paper for novelty/IP/value.
rank_papers_for_investor    Semantic retrieval + novelty/value ranking.
explain_score               Detailed feature + penalty breakdown.

Run
---
    python -m investor_signal_mcp.server
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Optional

from shared.config import settings
logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stderr),
        logging.FileHandler(Path(settings.log_dir) / "investor_signal_mcp.log"),
    ],
)
logger = logging.getLogger("investor_signal_mcp")

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("investor_signal", instructions=(
    "Score and rank research papers by investor-relevant signals. "
    "Outputs are research pattern indicators only — NOT investment advice."
))

from shared.db import (
    get_paper,
    get_papers_by_ids,
    init_db,
    update_investor_score,
)
from shared.embeddings import embed_single
from shared.models import FeatureScores, InvestorScore, Paper
from shared.vector_store import get_store

init_db()

# ── LLM-assisted novelty/IP/value scoring ─────────────────────────────────────

_NOVELTY_EVAL_SYSTEM_PROMPT = """
You are an investment-focused R&D diligence analyst.
Evaluate whether a research paper represents buildable, novel, and defensible
technology that can create investor value and potential IP.

Return ONLY valid JSON with this exact schema:
{
  "novelty": number,               // 0..1
  "investor_value": number,        // 0..1
  "buildability": number,          // 0..1
  "defensibility": number,         // 0..1
  "evidence_strength": number,     // 0..1
  "execution_risk": number,        // 0..1 (higher means riskier / worse)
  "conceptual_penalty": number,    // 0..1 (higher means too conceptual / hand-wavy)
  "top_signals": [string, string, string],
  "caveats": [string, string, string]
}

Scoring rubric checks:
1) Novel mechanism vs incremental iteration.
2) Can this be engineered with known tools in 12-24 months?
3) Is there concrete method detail (architecture, protocol, process), not just idea?
4) Is there proof of utility (benchmarks, experiments, prototype, pilot)?
5) Is there likely IP defensibility (patentability, know-how moat, data moat)?
6) Is there credible commercialization path and investor upside?
7) Penalize purely conceptual/speculative papers that lack implementation detail.
8) Penalize major dependency/regulatory/manufacturing bottlenecks.
""".strip()

_SCORE_WEIGHTS = {
    "novelty": 0.25,
    "investor_value": 0.23,
    "buildability": 0.22,
    "defensibility": 0.16,
    "evidence_strength": 0.14,
}


def _clamp_score(value: object, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _extract_json_object(text: str) -> dict:
    text = text.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return {}
    return {}


def _paper_evidence_text(paper: Paper) -> str:
    ocr_excerpt = (paper.ocr_text or "").strip()
    if ocr_excerpt:
        ocr_excerpt = ocr_excerpt[:6000]
    return (
        f"Title: {paper.title}\n"
        f"Year: {paper.year or 'unknown'}\n"
        f"Venue: {paper.venue or 'unknown'}\n"
        f"Fields: {', '.join(paper.fields_of_study) or 'unknown'}\n"
        f"Open Access: {'yes' if paper.is_open_access else 'no'}\n\n"
        f"Abstract:\n{paper.abstract or '(missing abstract)'}\n\n"
        f"OCR Excerpt (if available):\n{ocr_excerpt or '(no OCR text available)'}"
    )


def _profile_context(vc_profile: str) -> str:
    if not vc_profile.strip():
        return "No VC profile provided. Use a general deep-tech investor lens."
    return f"VC profile:\n{vc_profile.strip()}"


def _evaluate_with_llm(paper: Paper, vc_profile: str = "") -> Optional[dict]:
    if not settings.openai_api_key:
        return None

    try:
        import httpx

        user_prompt = (
            "Evaluate this paper for investor-grade novelty and value creation.\n"
            "Be strict and reduce scores if the paper is mostly conceptual.\n"
            "Tailor the score to the VC profile when one is provided.\n\n"
            f"{_profile_context(vc_profile)}\n\n"
            f"{_paper_evidence_text(paper)}"
        )
        payload = {
            "model": settings.openai_scoring_model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": _NOVELTY_EVAL_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        }
        base = settings.openai_base_url.rstrip("/")
        with httpx.Client(timeout=45) as client:
            resp = client.post(
                f"{base}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
        data = resp.json()
        message = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        parsed = _extract_json_object(message)
        return parsed if parsed else None
    except Exception as exc:
        logger.warning("LLM novelty evaluation failed for %s: %s", paper.paper_id, exc)
        return None


def _evaluate_with_fallback_heuristics(paper: Paper, vc_profile: str = "") -> dict:
    text = f"{paper.title} {paper.abstract or ''} {paper.ocr_text or ''}".lower()
    profile_text = vc_profile.lower()

    novelty_terms = ["novel", "first", "new paradigm", "breakthrough", "unprecedented"]
    build_terms = ["prototype", "implementation", "system", "hardware", "deployed", "fabricated"]
    evidence_terms = ["experiment", "benchmark", "ablation", "trial", "evaluation", "results"]
    conceptual_terms = ["framework", "vision", "perspective", "future work", "hypothesis"]
    moat_terms = ["patent", "proprietary", "manufacturing process", "trade-off", "know-how"]

    def _ratio(terms: list[str], denom: int = 4) -> float:
        return min(1.0, sum(1 for t in terms if t in text) / denom)

    novelty = _ratio(novelty_terms)
    buildability = _ratio(build_terms)
    evidence_strength = _ratio(evidence_terms)
    conceptual_penalty = _ratio(conceptual_terms, denom=3)
    defensibility = _ratio(moat_terms)
    investor_value = max(0.0, min(1.0, 0.45 * novelty + 0.35 * buildability + 0.20 * defensibility))
    execution_risk = max(0.0, min(1.0, 1.0 - (0.55 * buildability + 0.45 * evidence_strength)))
    profile_bonus = 0.0
    if profile_text:
        overlap_terms = [
            token for token in profile_text.replace(",", " ").split()
            if len(token) > 4 and token in text
        ]
        profile_bonus = min(0.1, 0.02 * len(set(overlap_terms)))
        investor_value = min(1.0, investor_value + profile_bonus)

    return {
        "novelty": round(novelty, 4),
        "investor_value": round(investor_value, 4),
        "buildability": round(buildability, 4),
        "defensibility": round(defensibility, 4),
        "evidence_strength": round(evidence_strength, 4),
        "execution_risk": round(execution_risk, 4),
        "conceptual_penalty": round(conceptual_penalty, 4),
        "top_signals": [
            "Fallback heuristic mode used (OPENAI_API_KEY missing/unavailable).",
            "Scores estimate novelty/buildability/evidence from paper text only.",
            "VC profile overlap applied heuristically." if profile_bonus else "No VC-profile-specific heuristic uplift applied.",
            "Use LLM scoring for stricter diligence quality.",
        ],
        "caveats": [
            "Heuristic scoring is less reliable than LLM rubric checks.",
            "No external market sizing or legal freedom-to-operate validation included.",
            "High score is not investment advice.",
        ],
    }


def compute_investor_score(paper: Paper, vc_profile: str = "") -> InvestorScore:
    """Score paper by novelty, buildability, IP potential, and investor value."""
    llm_eval = _evaluate_with_llm(paper, vc_profile=vc_profile)
    raw = llm_eval or _evaluate_with_fallback_heuristics(paper, vc_profile=vc_profile)

    features = FeatureScores(
        novelty=round(_clamp_score(raw.get("novelty")), 4),
        investor_value=round(_clamp_score(raw.get("investor_value")), 4),
        buildability=round(_clamp_score(raw.get("buildability")), 4),
        defensibility=round(_clamp_score(raw.get("defensibility")), 4),
        evidence_strength=round(_clamp_score(raw.get("evidence_strength")), 4),
        execution_risk=round(_clamp_score(raw.get("execution_risk")), 4),
        conceptual_penalty=round(_clamp_score(raw.get("conceptual_penalty")), 4),
    )

    base_score = sum(getattr(features, k) * w for k, w in _SCORE_WEIGHTS.items())
    risk_penalty = 0.12 * features.execution_risk
    conceptual_penalty = 0.18 * features.conceptual_penalty
    total = round(max(0.0, min(1.0, base_score - risk_penalty - conceptual_penalty)), 4)

    non_trivial = sum(
        1
        for k in ["novelty", "investor_value", "buildability", "defensibility", "evidence_strength"]
        if getattr(features, k) >= 0.4
    )
    confidence = round(min(1.0, 0.25 + non_trivial * 0.15 + (0.15 if llm_eval else 0.0)), 4)

    top_signals = raw.get("top_signals") or []
    caveats = raw.get("caveats") or []
    if not llm_eval:
        caveats.append("LLM analysis unavailable; fallback heuristics were used.")
    if not paper.abstract:
        caveats.append("Abstract missing; buildability and novelty confidence is reduced.")

    return InvestorScore(
        paper_id=paper.paper_id,
        title=paper.title,
        total_score=total,
        confidence=confidence,
        features=features,
        top_signals=[str(s) for s in top_signals][:5],
        caveats=[str(c) for c in caveats][:6],
    )


# ── MCP tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
def score_investor_relevance(paper_id: str) -> str:
    """Score a single paper for investor-relevant research signals.

    ⚠️  NOT INVESTMENT ADVICE.

    Args:
        paper_id: Semantic Scholar / OpenAlex paper ID.

    Returns:
        JSON InvestorScore with total_score (0–1), feature breakdown, and signals.
    """
    paper = get_paper(paper_id)
    if paper is None:
        return json.dumps({
            "error": f"Paper {paper_id!r} not found in local DB. "
                     "Run ingest_metadata first."
        })

    score = compute_investor_score(paper)
    update_investor_score(paper_id, score.total_score)
    return json.dumps(score.model_dump(), indent=2)


@mcp.tool()
def rank_papers_for_investor(
    query: str,
    top_k: int = 10,
    pass_threshold: Optional[float] = None,
) -> str:
    """Semantic retrieval + novelty/IP/value ranking for a research query.

    ⚠️  NOT INVESTMENT ADVICE.

    Args:
        query: Research topic (e.g. 'RNA therapeutics delivery').
        top_k: Number of top-ranked papers to return.
        pass_threshold: Minimum score to include in output (default from env).

    Returns:
        JSON ranked list with scores and feature highlights.
    """
    if pass_threshold is None:
        pass_threshold = settings.paper_pass_threshold

    store = get_store()
    if store.count() == 0:
        return json.dumps({
            "error": "Vector store is empty. Run embed_and_store_papers first."
        })

    # Retrieve wider candidate set then re-rank.
    candidates = min(top_k * 5, 100)
    query_vec = embed_single(query)
    hits = store.search(query_vec, top_k=candidates)
    candidate_ids = [h["paper_id"] for h in hits if h.get("paper_id")]
    papers = get_papers_by_ids(candidate_ids)

    scored = []
    for paper in papers:
        inv_score = compute_investor_score(paper)
        update_investor_score(paper.paper_id, inv_score.total_score)
        scored.append({
            "paper_id": paper.paper_id,
            "title": paper.title,
            "year": paper.year,
            "novelty_value_score": inv_score.total_score,
            "passes_threshold": inv_score.total_score >= pass_threshold,
            "top_signals": inv_score.top_signals[:3],
            "disclaimer": inv_score.disclaimer,
        })

    scored.sort(key=lambda x: x["novelty_value_score"], reverse=True)
    accepted = [s for s in scored if s["passes_threshold"]]
    return json.dumps({
        "query": query,
        "top_k": top_k,
        "pass_threshold": pass_threshold,
        "accepted_count": len(accepted),
        "ranked_papers": accepted[:top_k],
        "disclaimer": "⚠️  NOT INVESTMENT ADVICE.",
    }, indent=2)


@mcp.tool()
def explain_score(paper_id: str) -> str:
    """Return a detailed, human-readable breakdown of the investor relevance score.

    ⚠️  NOT INVESTMENT ADVICE.

    Args:
        paper_id: Semantic Scholar / OpenAlex paper ID.

    Returns:
        JSON with full feature scores, weight table, detected signals, and caveats.
    """
    paper = get_paper(paper_id)
    if paper is None:
        return json.dumps({"error": f"Paper {paper_id!r} not found in local DB."})

    score = compute_investor_score(paper)
    update_investor_score(paper_id, score.total_score)

    weights = _SCORE_WEIGHTS
    feature_table = [
        {
            "feature": k,
            "raw_score": round(getattr(score.features, k), 4),
            "weight": w,
            "contribution": round(getattr(score.features, k) * w, 4),
        }
        for k, w in weights.items()
    ]
    penalties = [
        {"feature": "execution_risk", "weight": -0.12, "contribution": round(-0.12 * score.features.execution_risk, 4)},
        {"feature": "conceptual_penalty", "weight": -0.18, "contribution": round(-0.18 * score.features.conceptual_penalty, 4)},
    ]

    return json.dumps({
        "paper_id": paper.paper_id,
        "title": paper.title,
        "year": paper.year,
        "venue": paper.venue,
        "total_novelty_value_score": score.total_score,
        "pass_threshold": settings.paper_pass_threshold,
        "passes_threshold": score.total_score >= settings.paper_pass_threshold,
        "confidence": score.confidence,
        "feature_breakdown": feature_table,
        "penalties": penalties,
        "top_signals": score.top_signals,
        "caveats": score.caveats,
        "disclaimer": score.disclaimer,
    }, indent=2)


# ── entrypoint ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("Starting investor_signal MCP server (stdio)")
    mcp.run(transport="stdio")
