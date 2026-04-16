"""investor_signal_mcp — Research-signal-based investor relevance scoring.

⚠️  NOT INVESTMENT ADVICE. Scores reflect transparent feature patterns only.

Tools
-----
score_investor_relevance    Score a single paper for investor-relevant signals.
rank_papers_for_investor    Semantic search + score ranking for a query.
explain_score               Detailed breakdown of an investor relevance score.

Run
---
    python -m investor_signal_mcp.server
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from shared.config import settings
from datetime import timezone as _tz

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
    list_papers,
    update_investor_score,
)
from shared.embeddings import embed_single
from shared.models import FeatureScores, InvestorScore, Paper
from shared.vector_store import get_store

init_db()

# ── Scoring knowledge bases ───────────────────────────────────────────────────

_CURRENT_YEAR = datetime.now(_tz.utc).year

# High-momentum research domains (2023-2026 signals).
_DOMAIN_MOMENTUM_TERMS = [
    "large language model", "llm", "foundation model", "generative ai",
    "diffusion model", "transformer", "gpt", "multimodal", "vision language",
    "protein structure", "alphafold", "drug discovery", "crispr", "gene therapy",
    "quantum computing", "quantum error correction", "qubit",
    "autonomous driving", "self-driving", "lidar",
    "battery", "solid-state battery", "energy storage",
    "fusion energy", "nuclear fusion",
    "semiconductor", "chip design", "neural processing unit",
    "climate model", "carbon capture",
    "mrna vaccine", "immunotherapy", "cancer immunotherapy",
]

# Translational / bench-to-market signals.
_TRANSLATIONAL_TERMS = [
    "state-of-the-art", "outperform", "benchmark", "real-world",
    "clinical trial", "fda", "ema", "regulatory", "clinical validation",
    "deployment", "production system", "scalable", "at scale",
    "proof of concept", "prototype", "pilot", "feasibility",
    "human evaluation", "user study", "ablation study",
    "zero-shot", "few-shot", "generaliz",
]

# Commercialisation / startup signals.
_COMMERCIAL_TERMS = [
    "startup", "spinoff", "spin-off", "venture", "commercializ",
    "industry partner", "industry collaboration", "corporate",
    "patent", "intellectual property", "ip agreement",
    "cost-effective", "low-cost", "affordable", "efficient",
    "open source", "open-source", "released publicly",
    "product", "service", "platform", "api",
    "enterprise", "business", "market",
]

# Top venue list for prestige scoring.
_TOP_VENUES = {
    "nature", "science", "cell", "new england journal", "lancet",
    "neurips", "nips", "icml", "iclr", "cvpr", "eccv", "iccv",
    "acl", "emnlp", "naacl", "sigkdd", "www", "sigir",
    "sosp", "osdi", "nsdi", "sigcomm", "usenix",
    "jacs", "nature chemistry", "nature medicine", "nature communications",
    "pnas", "nature biotechnology", "nature machine intelligence",
    "advanced materials", "acs nano",
}


# ── Feature computation ───────────────────────────────────────────────────────

def _keyword_score(text: str, terms: list[str]) -> float:
    """Fraction of terms present (0.0–1.0), capped at 1.0."""
    text_lower = text.lower()
    hits = sum(1 for t in terms if t in text_lower)
    return min(1.0, hits / max(1, len(terms) // 4))


def _recency_score(year: Optional[int]) -> float:
    if year is None:
        return 0.3
    age = max(0, _CURRENT_YEAR - year)
    if age == 0:
        return 1.0
    elif age <= 1:
        return 0.9
    elif age <= 2:
        return 0.75
    elif age <= 3:
        return 0.55
    elif age <= 5:
        return 0.35
    else:
        return max(0.0, 0.35 - (age - 5) * 0.05)


def _citation_velocity(citation_count: int, year: Optional[int]) -> float:
    """Estimated annual citation rate, normalised to 0–1."""
    if year is None:
        age = 3
    else:
        age = max(1, _CURRENT_YEAR - year)
    annual_rate = citation_count / age
    # Normalise: 100+ annual citations → 1.0
    return min(1.0, annual_rate / 100.0)


def _venue_prestige(venue: Optional[str]) -> float:
    if not venue:
        return 0.2
    venue_lower = venue.lower()
    for top in _TOP_VENUES:
        if top in venue_lower:
            return 1.0
    return 0.3


def _open_access_bonus(is_open_access: bool) -> float:
    return 0.8 if is_open_access else 0.2


def compute_investor_score(paper: Paper) -> InvestorScore:
    """Compute a transparent, feature-weighted investor relevance score."""
    text = f"{paper.title} {paper.abstract or ''} {' '.join(paper.fields_of_study)}"

    features = FeatureScores(
        recency=round(_recency_score(paper.year), 4),
        citation_velocity=round(_citation_velocity(paper.citation_count, paper.year), 4),
        domain_momentum=round(_keyword_score(text, _DOMAIN_MOMENTUM_TERMS), 4),
        translational_potential=round(_keyword_score(text, _TRANSLATIONAL_TERMS), 4),
        commercialization_hints=round(_keyword_score(text, _COMMERCIAL_TERMS), 4),
        open_access_bonus=round(_open_access_bonus(paper.is_open_access), 4),
        venue_prestige=round(_venue_prestige(paper.venue), 4),
    )

    # Weighted sum.
    weights = {
        "recency": 0.12,
        "citation_velocity": 0.22,
        "domain_momentum": 0.22,
        "translational_potential": 0.20,
        "commercialization_hints": 0.12,
        "open_access_bonus": 0.06,
        "venue_prestige": 0.06,
    }
    total = sum(getattr(features, k) * w for k, w in weights.items())
    total = round(total, 4)

    # Confidence: higher when more features have non-trivial values.
    non_trivial = sum(1 for k in weights if getattr(features, k) > 0.1)
    confidence = round(min(1.0, non_trivial / len(weights) + 0.1), 4)

    # Top signals (features scoring > 0.5).
    top_signals = []
    feature_labels = {
        "recency": f"Published {paper.year or 'recently'} (recency={features.recency:.2f})",
        "citation_velocity": f"{paper.citation_count} citations (velocity={features.citation_velocity:.2f})",
        "domain_momentum": f"High-momentum domain keywords (score={features.domain_momentum:.2f})",
        "translational_potential": f"Translational / benchmark signals (score={features.translational_potential:.2f})",
        "commercialization_hints": f"Commercialisation language detected (score={features.commercialization_hints:.2f})",
        "venue_prestige": f"Published in notable venue: {paper.venue or 'unknown'} (score={features.venue_prestige:.2f})",
    }
    for k, label in feature_labels.items():
        if getattr(features, k) > 0.4:
            top_signals.append(label)

    caveats = [
        "Score is based on text pattern matching — not peer-reviewed analysis.",
        "Citation counts may lag behind recent publications.",
        "High score does not imply feasibility, IP freedom, or market demand.",
    ]
    if not paper.abstract:
        caveats.append("Abstract missing — domain/translational scores may be underestimated.")

    return InvestorScore(
        paper_id=paper.paper_id,
        title=paper.title,
        total_score=total,
        confidence=confidence,
        features=features,
        top_signals=top_signals,
        caveats=caveats,
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
def rank_papers_for_investor(query: str, top_k: int = 10) -> str:
    """Semantic search + investor ranking for a research query.

    Retrieves semantically relevant papers from the vector store, then
    re-ranks by investor relevance score.

    ⚠️  NOT INVESTMENT ADVICE.

    Args:
        query: Research topic (e.g. 'RNA therapeutics delivery').
        top_k: Number of top-ranked papers to return.

    Returns:
        JSON ranked list with scores and feature highlights.
    """
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
        # Blended score: 60% semantic, 40% investor signal.
        sem_score = next(
            (h["score"] for h in hits if h.get("paper_id") == paper.paper_id), 0.5
        )
        blended = round(0.6 * sem_score + 0.4 * inv_score.total_score, 4)
        scored.append({
            "paper_id": paper.paper_id,
            "title": paper.title,
            "year": paper.year,
            "citation_count": paper.citation_count,
            "semantic_score": round(sem_score, 4),
            "investor_score": inv_score.total_score,
            "blended_score": blended,
            "top_signals": inv_score.top_signals[:3],
            "disclaimer": inv_score.disclaimer,
        })

    scored.sort(key=lambda x: x["blended_score"], reverse=True)
    return json.dumps({
        "query": query,
        "top_k": top_k,
        "ranked_papers": scored[:top_k],
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

    weights = {
        "recency": 0.12,
        "citation_velocity": 0.22,
        "domain_momentum": 0.22,
        "translational_potential": 0.20,
        "commercialization_hints": 0.12,
        "open_access_bonus": 0.06,
        "venue_prestige": 0.06,
    }
    feature_table = [
        {
            "feature": k,
            "raw_score": round(getattr(score.features, k), 4),
            "weight": w,
            "contribution": round(getattr(score.features, k) * w, 4),
        }
        for k, w in weights.items()
    ]

    return json.dumps({
        "paper_id": paper.paper_id,
        "title": paper.title,
        "year": paper.year,
        "venue": paper.venue,
        "citation_count": paper.citation_count,
        "total_investor_score": score.total_score,
        "confidence": score.confidence,
        "feature_breakdown": feature_table,
        "top_signals": score.top_signals,
        "caveats": score.caveats,
        "disclaimer": score.disclaimer,
    }, indent=2)


# ── entrypoint ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("Starting investor_signal MCP server (stdio)")
    mcp.run(transport="stdio")
