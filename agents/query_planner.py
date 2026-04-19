"""Query Planner Agent.

Given a VC profile, generate a small set of well-reasoned search queries for
OpenAlex. Avoids dumping sector keywords — instead, the agent reasons about
what *kinds* of papers would be signal for this particular thesis and emits
diverse, targeted queries.

In autonomous mode, the planner also receives the list of already-covered
angles so it can broaden coverage rather than re-searching.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from shared.config import settings
from shared.models import VCProfile
from tools.llm import call_llm

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """\
You are a research scout for a venture capital firm. Your job is to translate a
VC thesis into a short list of targeted academic search queries for OpenAlex.

Rules:
1. Think about WHAT kind of research would represent an investable signal
   given this thesis — not just sector keywords.
2. Prefer specific, mechanism-level phrases (e.g., "electrocatalytic CO2
   reduction to ethylene on copper" beats "carbon capture").
3. Each query should probe a *different angle*: technology, application,
   mechanism, bottleneck, or emerging approach.
4. Avoid duplicates and near-duplicates.
5. Output strict JSON only — no prose, no markdown fences.

Output schema:
{
  "reasoning": "2-3 sentences explaining your overall angle selection",
  "queries": [
    {"query": "...", "angle": "short tag for what this probes"}
  ]
}
"""


def _build_user_prompt(profile: VCProfile, n_queries: int, exclude_angles: list[str]) -> str:
    exclude_block = ""
    if exclude_angles:
        exclude_block = (
            "\nAngles ALREADY covered in earlier rounds — do NOT repeat these:\n"
            + "\n".join(f"  - {a}" for a in exclude_angles)
            + "\nPropose FRESH angles that broaden coverage."
        )

    sectors = ", ".join(profile.sectors) if profile.sectors else "(none specified)"
    geo = ", ".join(profile.geography) if profile.geography else "(any)"
    deal_breakers = "; ".join(profile.deal_breakers) if profile.deal_breakers else "(none)"

    return f"""\
VC Thesis:
{profile.thesis or "(no thesis provided)"}

Target sectors: {sectors}
Target stage: {profile.stage}
Geography: {geo}
Deal-breakers: {deal_breakers}
Publication window: {profile.year_from}–{profile.year_to or "present"}
{exclude_block}

Emit exactly {n_queries} queries. Output JSON only."""


def _extract_json(text: str) -> dict:
    """Best-effort JSON extraction from an LLM response."""
    text = text.strip()
    # Strip ```json ... ``` fences if present
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    # Find first balanced {...}
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found in response")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise ValueError("Unterminated JSON object")


def plan_queries(
    profile: VCProfile,
    n_queries: int = 6,
    exclude_angles: Optional[list[str]] = None,
) -> list[dict]:
    """Return a list of {'query': str, 'angle': str} dicts.

    Falls back to profile.sectors as plain queries if the LLM response is malformed.
    """
    user = _build_user_prompt(profile, n_queries, exclude_angles or [])
    logger.info("Query planner: requesting %d queries from %s", n_queries, settings.planner_model)
    raw = call_llm(settings.planner_model, SYSTEM_PROMPT, user, temperature=0.4)

    try:
        parsed = _extract_json(raw)
        queries = parsed.get("queries") or []
        cleaned: list[dict] = []
        seen: set[str] = set()
        for q in queries:
            text = (q.get("query") or "").strip()
            angle = (q.get("angle") or "").strip() or "general"
            if not text or text.lower() in seen:
                continue
            seen.add(text.lower())
            cleaned.append({"query": text, "angle": angle})
        if cleaned:
            logger.info("Planner produced %d queries", len(cleaned))
            return cleaned[:n_queries]
        logger.warning("Planner returned empty queries; falling back")
    except Exception as exc:
        logger.warning("Planner JSON parse failed (%s); falling back", exc)

    # Fallback: sector keywords as queries.
    fallback = [{"query": s, "angle": s} for s in (profile.sectors or ["frontier technology"])]
    return fallback[:n_queries]
