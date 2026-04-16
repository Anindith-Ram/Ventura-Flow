"""Qdrant vector store wrapper.

Connection modes (in priority order):
  1. QDRANT_URL is set → connect to remote/Docker Qdrant server.
  2. Otherwise         → in-memory Qdrant (development / CI friendly).

In-memory mode is ephemeral; restart loses all vectors.
For persistence without Docker run:
    docker run -p 6333:6333 -v $(pwd)/data/qdrant:/qdrant/storage qdrant/qdrant
then set QDRANT_URL=http://localhost:6333
"""

from __future__ import annotations

import logging
from typing import Optional

from shared.config import settings

logger = logging.getLogger(__name__)

# ── lazy singleton ─────────────────────────────────────────────────────────────
_store: Optional["VectorStore"] = None


def get_store() -> "VectorStore":
    global _store
    if _store is None:
        _store = VectorStore()
    return _store


class VectorStore:
    def __init__(self) -> None:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams

        if settings.qdrant_url:
            logger.info("Connecting to Qdrant at %s", settings.qdrant_url)
            self.client = QdrantClient(
                url=settings.qdrant_url,
                api_key=settings.qdrant_api_key or None,
            )
        else:
            logger.info("Using in-memory Qdrant (set QDRANT_URL for persistence)")
            self.client = QdrantClient(":memory:")

        self.collection = settings.qdrant_collection
        self.dim = settings.embedding_dim
        self._ensure_collection()

    # ── collection management ──────────────────────────────────────────────────

    def _ensure_collection(self) -> None:
        from qdrant_client.models import Distance, VectorParams

        existing = [c.name for c in self.client.get_collections().collections]
        if self.collection not in existing:
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=self.dim, distance=Distance.COSINE),
            )
            logger.info("Created Qdrant collection '%s' (dim=%d)", self.collection, self.dim)

    # ── write ──────────────────────────────────────────────────────────────────

    def upsert(self, paper_id: str, vector: list[float], payload: dict) -> None:
        """Store a single embedding with metadata payload."""
        from qdrant_client.models import PointStruct

        self.client.upsert(
            collection_name=self.collection,
            points=[PointStruct(id=self._hash_id(paper_id), vector=vector, payload=payload)],
        )

    def upsert_batch(self, records: list[tuple[str, list[float], dict]]) -> None:
        """Bulk upsert: list of (paper_id, vector, payload)."""
        from qdrant_client.models import PointStruct

        points = [
            PointStruct(id=self._hash_id(pid), vector=vec, payload=meta)
            for pid, vec, meta in records
        ]
        self.client.upsert(collection_name=self.collection, points=points)

    # ── read ──────────────────────────────────────────────────────────────────

    def search(self, query_vector: list[float], top_k: int = 10) -> list[dict]:
        """Return top_k nearest neighbours with score and payload.

        Uses query_points (qdrant-client >= 1.7) with search fallback.
        """
        try:
            # qdrant-client >= 1.7 API
            response = self.client.query_points(
                collection_name=self.collection,
                query=query_vector,
                limit=top_k,
                with_payload=True,
            )
            scored = response.points
        except AttributeError:
            # Legacy fallback (qdrant-client < 1.7)
            scored = self.client.search(  # type: ignore[attr-defined]
                collection_name=self.collection,
                query_vector=query_vector,
                limit=top_k,
                with_payload=True,
            )

        return [
            {"paper_id": r.payload.get("paper_id", ""), "score": r.score, **r.payload}
            for r in scored
        ]

    def get_vector(self, paper_id: str) -> Optional[list[float]]:
        """Retrieve stored embedding for a paper; None if not found."""
        results = self.client.retrieve(
            collection_name=self.collection,
            ids=[self._hash_id(paper_id)],
            with_vectors=True,
        )
        if not results:
            return None
        vec = results[0].vector
        # qdrant-client may return a named dict; normalise to flat list.
        if isinstance(vec, dict):
            vec = vec.get("", list(vec.values())[0] if vec else [])
        return list(vec) if vec is not None else None  # type: ignore[return-value]

    def get_all_vectors(self, limit: int = 5000) -> list[tuple[str, list[float]]]:
        """Fetch all (paper_id, vector) pairs for clustering."""
        scroll_result = self.client.scroll(
            collection_name=self.collection,
            limit=limit,
            with_vectors=True,
            with_payload=True,
        )
        # scroll() returns (records, next_page_offset) in all versions.
        records = scroll_result[0] if isinstance(scroll_result, tuple) else scroll_result.points
        out = []
        for r in records:
            vec = r.vector
            if isinstance(vec, dict):
                vec = list(vec.values())[0] if vec else []
            if vec:
                out.append((r.payload.get("paper_id", str(r.id)), list(vec)))
        return out

    def count(self) -> int:
        info = self.client.get_collection(self.collection)
        return info.points_count or 0

    # ── helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _hash_id(paper_id: str) -> int:
        """Map a string paper ID to a stable uint64 for Qdrant."""
        import hashlib

        digest = hashlib.md5(paper_id.encode()).digest()
        # Take first 8 bytes as unsigned int; keep within uint64 range.
        value = int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF
        return value
