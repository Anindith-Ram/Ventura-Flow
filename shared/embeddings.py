"""Local embeddings via fastembed (ONNX, no API key, no server)."""

from __future__ import annotations

import logging

import numpy as np

from shared.config import settings

logger = logging.getLogger(__name__)

_model = None


def _get_model():
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        logger.info("Loading fastembed model: %s (first run downloads ~130 MB)", settings.embedding_model)
        _model = TextEmbedding(model_name=settings.embedding_model)
    return _model


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    model = _get_model()
    return [v.tolist() for v in model.embed(texts)]


def embed_single(text: str) -> list[float]:
    return embed_texts([text])[0]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if denom == 0:
        return 0.0
    return float(np.dot(va, vb) / denom)


def cosine_matrix(vectors: list[list[float]]) -> np.ndarray:
    """Pairwise cosine similarity for a batch of vectors."""
    if not vectors:
        return np.zeros((0, 0), dtype=np.float32)
    m = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    normed = m / norms
    return normed @ normed.T
