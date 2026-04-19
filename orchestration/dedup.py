"""Abstract-level near-duplicate detection via fastembed cosine similarity."""

from __future__ import annotations

import logging
import numpy as np

from shared.config import settings
from shared.embeddings import cosine_matrix, embed_texts
from shared.models import Paper

logger = logging.getLogger(__name__)


def dedupe_papers(papers: list[Paper]) -> list[Paper]:
    """Return papers with near-duplicates removed.

    Keeps the first occurrence in the input order (so pre-sort by desired
    priority — e.g. citation_count desc — before calling).
    """
    if len(papers) < 2:
        return list(papers)

    texts = [p.text_for_embedding for p in papers]
    vectors = embed_texts(texts)
    if not vectors:
        return list(papers)

    sims = cosine_matrix(vectors)
    threshold = settings.dedup_cosine_threshold
    dropped: set[int] = set()
    for i in range(len(papers)):
        if i in dropped:
            continue
        for j in range(i + 1, len(papers)):
            if j in dropped:
                continue
            if sims[i, j] >= threshold:
                dropped.add(j)

    kept = [p for idx, p in enumerate(papers) if idx not in dropped]
    if dropped:
        logger.info("Dedup: removed %d near-duplicates (threshold=%.2f)", len(dropped), threshold)
    return kept
