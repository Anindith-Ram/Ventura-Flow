"""memory_mcp — MCP server for vector embedding, semantic search, and clustering.

Tools
-----
embed_and_store_papers    Generate and store embeddings for papers in DB.
semantic_search           Query the vector store with a natural-language string.
find_similar_papers       Find papers similar to a known paper by ID.
cluster_topics            Cluster all embedded papers by topic.
get_paper_feature_vector  Retrieve the stored embedding metadata for a paper.

Run
---
    python -m memory_mcp.server
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
        logging.FileHandler(Path(settings.log_dir) / "memory_mcp.log"),
    ],
)
logger = logging.getLogger("memory_mcp")

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("memory", instructions=(
    "Embed paper text into vectors, store in Qdrant, and perform semantic "
    "search and topic clustering across the paper corpus."
))

from shared.db import (
    init_db,
    get_papers_by_ids,
    list_unembedded_papers,
    mark_embedded,
)
from shared.embeddings import embed_texts, embed_single
from shared.models import ClusterResult
from shared.vector_store import get_store

init_db()


# ── helpers ───────────────────────────────────────────────────────────────────

def _paper_summary(payload: dict) -> dict:
    return {
        "paper_id": payload.get("paper_id", ""),
        "title": payload.get("title", ""),
        "year": payload.get("year"),
        "venue": payload.get("venue"),
        "citation_count": payload.get("citation_count", 0),
        "source": payload.get("source", ""),
    }


# ── MCP tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
def embed_and_store_papers(paper_ids: list[str]) -> str:
    """Generate embeddings for the given papers and store them in Qdrant.

    If paper_ids is empty, embeds ALL un-embedded papers in the local DB
    (up to 500 at a time).

    Args:
        paper_ids: List of paper IDs to embed. Pass [] to embed all pending.

    Returns:
        JSON with count of newly embedded papers.
    """
    store = get_store()

    if paper_ids:
        papers = get_papers_by_ids(paper_ids)
    else:
        papers = list_unembedded_papers(limit=500)

    if not papers:
        return json.dumps({"embedded": 0, "message": "No papers to embed."})

    texts = [p.text_for_embedding for p in papers]
    logger.info("Generating embeddings for %d papers…", len(papers))
    vectors = embed_texts(texts)

    records = []
    for paper, vec in zip(papers, vectors):
        payload = {
            "paper_id": paper.paper_id,
            "title": paper.title,
            "abstract": paper.abstract or "",
            "year": paper.year,
            "venue": paper.venue or "",
            "citation_count": paper.citation_count,
            "is_open_access": paper.is_open_access,
            "fields_of_study": paper.fields_of_study,
            "source": paper.source,
        }
        records.append((paper.paper_id, vec, payload))

    store.upsert_batch(records)
    mark_embedded([p.paper_id for p in papers])
    logger.info("Embedded and stored %d papers in Qdrant", len(papers))

    return json.dumps({
        "embedded": len(papers),
        "total_in_store": store.count(),
        "paper_ids": [p.paper_id for p in papers],
    }, indent=2)


@mcp.tool()
def semantic_search(query: str, top_k: int = 10) -> str:
    """Search the vector store with a natural-language query.

    Args:
        query: Free-text semantic query (e.g. 'large language models for code').
        top_k: Number of results to return (default 10).

    Returns:
        JSON list of matching papers with similarity scores.
    """
    store = get_store()
    if store.count() == 0:
        return json.dumps({
            "error": "Vector store is empty. Run embed_and_store_papers first."
        })

    query_vec = embed_single(query)
    hits = store.search(query_vec, top_k=top_k)
    results = [
        {**_paper_summary(h), "similarity_score": round(h["score"], 4)}
        for h in hits
    ]
    return json.dumps({"query": query, "top_k": top_k, "results": results}, indent=2)


@mcp.tool()
def find_similar_papers(paper_id: str, top_k: int = 10) -> str:
    """Find papers most similar to the given paper using its stored embedding.

    Args:
        paper_id: ID of the reference paper (must already be embedded).
        top_k:    Number of similar papers to return.

    Returns:
        JSON list of similar papers with cosine similarity scores.
    """
    store = get_store()
    vec = store.get_vector(paper_id)
    if vec is None:
        return json.dumps({
            "error": f"No embedding found for paper_id={paper_id!r}. "
                     "Run embed_and_store_papers first."
        })

    hits = store.search(vec, top_k=top_k + 1)  # +1 because paper itself may appear
    results = [
        {**_paper_summary(h), "similarity_score": round(h["score"], 4)}
        for h in hits
        if h.get("paper_id") != paper_id
    ][:top_k]
    return json.dumps({"reference_paper_id": paper_id, "similar": results}, indent=2)


@mcp.tool()
def cluster_topics(min_cluster_size: int = 3, n_clusters: Optional[int] = None) -> str:
    """Cluster all embedded papers into topic groups using KMeans.

    Args:
        min_cluster_size: Minimum papers required to form a cluster (default 3).
        n_clusters:       Override number of clusters (default: auto-select via
                          elbow heuristic).

    Returns:
        JSON list of clusters with representative papers and top terms.
    """
    import numpy as np
    from sklearn.cluster import KMeans
    from sklearn.feature_extraction.text import TfidfVectorizer

    store = get_store()
    all_vecs = store.get_all_vectors(limit=5000)

    if len(all_vecs) < min_cluster_size * 2:
        return json.dumps({
            "error": f"Need at least {min_cluster_size * 2} embedded papers; "
                     f"have {len(all_vecs)}. Run embed_and_store_papers first."
        })

    ids = [pid for pid, _ in all_vecs]
    matrix = np.array([vec for _, vec in all_vecs], dtype=np.float32)

    # Auto-select k if not given.
    if n_clusters is None:
        n_clusters = max(2, min(len(ids) // max(min_cluster_size, 1), 20))

    logger.info("Clustering %d papers into %d clusters", len(ids), n_clusters)
    km = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    labels = km.fit_predict(matrix)

    # Group papers by cluster.
    from collections import defaultdict
    clusters: dict[int, list[str]] = defaultdict(list)
    for pid, label in zip(ids, labels):
        clusters[int(label)].append(pid)

    # Fetch papers from DB for TF-IDF term extraction.
    from shared.db import get_papers_by_ids as _get_papers
    cluster_results = []
    for cid, pids in sorted(clusters.items(), key=lambda x: -len(x[1])):
        if len(pids) < min_cluster_size:
            continue
        cluster_papers = _get_papers(pids[:20])  # limit for TF-IDF

        # Extract top terms via TF-IDF.
        texts = [f"{p.title} {p.abstract or ''}" for p in cluster_papers]
        top_terms: list[str] = []
        if texts:
            try:
                vec = TfidfVectorizer(max_features=50, stop_words="english")
                tfidf = vec.fit_transform(texts)
                top_terms = list(vec.get_feature_names_out()[:8])
            except Exception:
                pass

        # Representative papers = closest to centroid.
        centroid = km.cluster_centers_[cid]
        idxs_in_cluster = [i for i, lbl in enumerate(labels) if lbl == cid]
        dists = np.linalg.norm(matrix[idxs_in_cluster] - centroid, axis=1)
        top_idx = idxs_in_cluster[int(np.argmin(dists))]
        representative_ids = [ids[top_idx]] + [p.paper_id for p in cluster_papers[:3]]
        representative_ids = list(dict.fromkeys(representative_ids))[:3]  # dedup, keep order

        cluster_results.append(
            ClusterResult(
                cluster_id=cid,
                size=len(pids),
                representative_paper_ids=representative_ids,
                top_terms=top_terms,
            ).model_dump()
        )

    return json.dumps({
        "n_papers": len(ids),
        "n_clusters": len(cluster_results),
        "clusters": cluster_results,
    }, indent=2)


@mcp.tool()
def get_paper_feature_vector(paper_id: str) -> str:
    """Retrieve metadata about the stored embedding for a paper.

    Args:
        paper_id: OpenAlex paper ID.

    Returns:
        JSON with embedding dimension and first 16 values (preview).
    """
    store = get_store()
    vec = store.get_vector(paper_id)
    if vec is None:
        return json.dumps({
            "error": f"No embedding found for {paper_id!r}. "
                     "Run embed_and_store_papers first."
        })

    return json.dumps({
        "paper_id": paper_id,
        "embedding_dim": len(vec),
        "backend": settings.embedding_backend,
        "model": settings.embedding_model,
        "vector_preview": [round(v, 6) for v in vec[:16]],
        "norm": round(float(sum(x**2 for x in vec) ** 0.5), 6),
    }, indent=2)


# ── entrypoint ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("Starting memory MCP server (stdio)")
    mcp.run(transport="stdio")
