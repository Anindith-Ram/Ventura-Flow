"""Diversity-aware top-K selection.

Given a ranked list of triage scores, return the top-K subject to:
  - min floor (settings.triage_min_papers) — always keep at least this many
  - percentile target (settings.triage_top_percentile of total) — soft target
  - subfield cap (settings.diversity_max_per_subfield) — enforce spread
"""

from __future__ import annotations

import logging
from collections import Counter

from shared.config import settings
from shared.models import TriageScore

logger = logging.getLogger(__name__)


def select_top(
    scores: list[TriageScore],
    total_universe: int,
    enforce_diversity: bool = True,
) -> list[TriageScore]:
    """Return the papers that pass the triage gate."""
    if not scores:
        return []

    # Sort by composite desc
    ranked = sorted(scores, key=lambda s: s.composite, reverse=True)

    # Target size = max(min_papers, ceil(percentile * universe)), capped at max_papers
    import math
    pct_target = math.ceil(settings.triage_top_percentile * total_universe)
    target = max(settings.triage_min_papers, pct_target)
    target = min(target, settings.triage_max_papers, len(ranked))

    if not enforce_diversity:
        return ranked[:target]

    # Subfield cap: pick greedily in score order, skipping once a subfield is full.
    kept: list[TriageScore] = []
    counts: Counter[str] = Counter()
    for s in ranked:
        if counts[s.subfield] >= settings.diversity_max_per_subfield:
            continue
        kept.append(s)
        counts[s.subfield] += 1
        if len(kept) >= target:
            break

    # Fill shortfall with best remaining (ignoring diversity) so we always hit target.
    if len(kept) < target:
        already = {s.paper_id for s in kept}
        for s in ranked:
            if s.paper_id in already:
                continue
            kept.append(s)
            if len(kept) >= target:
                break

    logger.info(
        "Diversity select: kept %d of %d (target=%d, subfields=%s)",
        len(kept), len(ranked), target, dict(Counter(s.subfield for s in kept))
    )
    return kept
