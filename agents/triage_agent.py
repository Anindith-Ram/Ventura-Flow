"""Triage Agent.

For each candidate paper (title + abstract + author metrics), produces:
  - vc_fit (0-100): semantic alignment with VC thesis
  - novelty (0-100): signal-level originality heuristic
  - credibility (0-100): author track record + citation patterns
  - composite: weighted blend (weights from VCProfile)
  - rationale: 1-sentence "why"
  - subfield: short tag used for diversity enforcement

Batched: one LLM call per paper (qwen3:8b is fast). Scores + rationale let
the dashboard show a tooltip explaining each ranking.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from shared.config import settings
from shared.models import Paper, TriageScore, VCProfile
from tools.llm import call_llm

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """\
You are a triage analyst at a venture capital firm. For a candidate research
paper, produce a structured assessment against the VC thesis.

Score each dimension 0-100:
- vc_fit:      Does the paper's core contribution match the thesis? Reason about
               *what the paper enables*, not keyword overlap.
- novelty:     How new is the contribution relative to the general literature?
               Incremental extensions score low; genuinely new mechanisms,
               approaches, or capabilities score high.
- credibility: Does author track record + citation patterns suggest this is
               serious work? Junior authors with weak affiliations should not
               be disqualified if the work itself is strong — weigh both.

Pick a short subfield tag (2-4 words) for diversity bucketing.

Write a ONE-SENTENCE rationale: why this paper got its composite score. This
rationale will be shown to the VC as a tooltip, so be concrete and specific.

Output strict JSON only:
{
  "vc_fit": <0-100>,
  "novelty": <0-100>,
  "credibility": <0-100>,
  "subfield": "...",
  "rationale": "..."
}
"""


def _author_block(paper: Paper) -> str:
    if not paper.authors:
        return "(no author info)"
    lines = []
    for a in paper.authors[:6]:
        parts = [a.name]
        if a.h_index is not None:
            parts.append(f"h-index {a.h_index}")
        if a.works_count:
            parts.append(f"{a.works_count} works")
        if a.affiliations:
            parts.append(a.affiliations[0])
        lines.append(" / ".join(parts))
    return "\n".join(f"  - {l}" for l in lines)


def _build_user_prompt(paper: Paper, profile: VCProfile) -> str:
    return f"""\
═══ VC THESIS ═══
{profile.thesis or "(no thesis)"}

Sectors of interest: {", ".join(profile.sectors) if profile.sectors else "(unspecified)"}
Deal-breakers: {"; ".join(profile.deal_breakers) if profile.deal_breakers else "(none)"}

═══ CANDIDATE PAPER ═══
Title: {paper.title}
Year: {paper.year}
Venue: {paper.venue or "(unknown)"}
Citations: {paper.citation_count}
Fields: {", ".join(paper.fields_of_study) if paper.fields_of_study else "(unlabelled)"}

Authors:
{_author_block(paper)}

Abstract:
{(paper.abstract or "(abstract unavailable)")[:1500]}

Output JSON only."""


def _extract_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON in response")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise ValueError("Unterminated JSON")


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return 0.0


def triage_paper(paper: Paper, profile: VCProfile) -> TriageScore:
    user = _build_user_prompt(paper, profile)
    try:
        raw = call_llm(settings.triage_model, SYSTEM_PROMPT, user, temperature=0.2)
        parsed = _extract_json(raw)
    except Exception as exc:
        logger.warning("Triage failed for %s: %s", paper.paper_id, exc)
        return TriageScore(
            paper_id=paper.paper_id,
            vc_fit=0.0, novelty=0.0, credibility=0.0, composite=0.0,
            rationale="Triage error — defaulting to 0.",
            subfield=(paper.fields_of_study[0] if paper.fields_of_study else "unknown"),
        )

    vc_fit = _clamp(parsed.get("vc_fit", 0))
    novelty = _clamp(parsed.get("novelty", 0))
    credibility = _clamp(parsed.get("credibility", 0))
    composite = (
        profile.weight_vc_fit * vc_fit
        + profile.weight_novelty * novelty
        + profile.weight_author_credibility * credibility
    )
    # Soft h-index bonus/penalty: up to ±5 points
    if profile.min_h_index > 0:
        max_h = paper.max_author_h_index
        if max_h >= profile.min_h_index:
            composite = min(100.0, composite + 3.0)
        else:
            composite = max(0.0, composite - 2.0)

    return TriageScore(
        paper_id=paper.paper_id,
        vc_fit=vc_fit,
        novelty=novelty,
        credibility=credibility,
        composite=round(composite, 2),
        rationale=(parsed.get("rationale") or "").strip()[:300],
        subfield=(parsed.get("subfield") or "").strip().lower() or "unknown",
    )


def triage_batch(papers: list[Paper], profile: VCProfile) -> list[TriageScore]:
    return [triage_paper(p, profile) for p in papers]
