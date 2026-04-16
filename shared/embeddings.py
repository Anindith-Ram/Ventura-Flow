"""Provider-agnostic embedding interface.

Backends
--------
fastembed  (default) — local ONNX inference, no API key needed.
openai               — OpenAI embeddings API (or compatible endpoint).
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from shared.config import settings

logger = logging.getLogger(__name__)

# ── lazy singletons ───────────────────────────────────────────────────────────
_fastembed_model = None
_openai_client = None


def _get_fastembed():
    global _fastembed_model
    if _fastembed_model is None:
        try:
            from fastembed import TextEmbedding
            logger.info("Loading fastembed model: %s (first run downloads ~130 MB)", settings.embedding_model)
            _fastembed_model = TextEmbedding(model_name=settings.embedding_model)
            logger.info("fastembed model loaded.")
        except ImportError as exc:
            raise RuntimeError(
                "fastembed is not installed. Run: uv sync"
            ) from exc
    return _fastembed_model


def _get_openai():
    global _openai_client
    if _openai_client is None:
        try:
            import openai
            _openai_client = openai.OpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
            )
        except ImportError as exc:
            raise RuntimeError("openai package not installed. Run: uv add openai") from exc
    return _openai_client


# ── public API ────────────────────────────────────────────────────────────────

def embed_texts(texts: list[str]) -> list[list[float]]:
    """Return a list of embedding vectors, one per input text."""
    if not texts:
        return []

    backend = settings.embedding_backend.lower()

    if backend == "fastembed":
        model = _get_fastembed()
        # fastembed returns a generator of numpy arrays
        vectors = list(model.embed(texts))
        return [v.tolist() for v in vectors]

    elif backend == "openai":
        client = _get_openai()
        response = client.embeddings.create(
            model=settings.openai_embedding_model,
            input=texts,
        )
        return [item.embedding for item in response.data]

    else:
        raise ValueError(f"Unknown EMBEDDING_BACKEND: {backend!r}. Use 'fastembed' or 'openai'.")


def embed_single(text: str) -> list[float]:
    """Embed a single string."""
    return embed_texts([text])[0]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    if denom == 0:
        return 0.0
    return float(np.dot(va, vb) / denom)
