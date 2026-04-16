# Research Intelligence Pipeline

An end-to-end academic research intelligence system exposing paper search, semantic memory, and investor-signal scoring as MCP tools callable from OpenCode.

> **Disclaimer:** Investor relevance scores are research pattern indicators only. **NOT investment advice.**

---

## Architecture

```
papers_mcp          memory_mcp          investor_signal_mcp
    │                   │                        │
    ▼                   ▼                        ▼
Semantic Scholar    Qdrant (vector DB)    Feature scoring
OpenAlex            fastembed             (recency, citations,
    │                   │                 momentum, OCR signals)
    └──────────────────┬┘                        │
                       │                         │
                  SQLite (papers.db)              │
                       │                         │
                  orchestration/pipeline.py ──────┘
                       │
                  PaddleOCR MCP (OCR gating)
```

---

## Setup

### 1. Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- [OpenCode](https://opencode.ai/) CLI

### 2. Install dependencies

```bash
cd "Project Personal"
uv sync
```

This installs all packages into `.venv/` including:
- `fastembed` (ONNX local embeddings, ~130 MB model download on first use)
- `qdrant-client` (in-memory vector store, no Docker required)
- `mcp`, `httpx`, `tenacity`, `scikit-learn`, `pymupdf`, `rich`

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env — minimum required for offline mode: nothing!
# Add S2_API_KEY for higher Semantic Scholar rate limits.
# Add OPENAI_API_KEY + set EMBEDDING_BACKEND=openai for cloud embeddings.
```

### 4. (Optional) Persistent vector store via Docker

By default vectors are in-memory (lost on restart).  
For persistence, start Qdrant and set `QDRANT_URL`:

```bash
docker run -d -p 6333:6333 -v $(pwd)/data/qdrant:/qdrant/storage qdrant/qdrant
echo "QDRANT_URL=http://localhost:6333" >> .env
```

---

## Run Commands

### Start individual MCP servers (for testing)

```bash
# Papers ingestion
uv run python -m papers_mcp.server

# Vector memory
uv run python -m memory_mcp.server

# Investor signal scoring
uv run python -m investor_signal_mcp.server

# Full pipeline (CLI mode)
uv run python -m orchestration.pipeline --query "RNA therapeutics" --limit 20
```

### Run the end-to-end test

```bash
uv run python scripts/test_pipeline.py
# Custom query:
uv run python scripts/test_pipeline.py --query "CRISPR cancer" --limit 20 --ocr-threshold 0.55
```

---

## OpenCode Usage

After running `uv sync`, the three MCP servers are registered in `~/.config/opencode/opencode.json`.  
Start OpenCode and verify:

```
/mcps
```

You should see `paddleocr`, `papers`, `memory`, and `investor_signal` listed.

### Sample prompts

```
# Ingest papers
Use the papers MCP to ingest 20 papers on "protein language models"

# Semantic search
Search my vector memory for papers about "drug target identification"

# Investor ranking
Rank the stored papers for investor relevance on the topic of "mRNA delivery systems"

# Full pipeline
Run the pipeline for "quantum error correction" with limit=20

# Explain a score
Explain the investor score for paper <paper_id>

# Find similar
Find the 5 most similar papers to <paper_id>

# Cluster topics
Cluster my stored papers into topic groups
```

---

## MCP Tool Reference

### `papers` server

| Tool | Description |
|------|-------------|
| `search_papers(query, limit, year_from?, year_to?)` | Search S2 + OpenAlex, return metadata |
| `get_paper_details(paper_id_or_doi)` | Full details for one paper |
| `ingest_metadata(query, limit, filters?)` | Search + upsert into SQLite |
| `ingest_by_ids(ids[])` | Ingest specific papers by ID/DOI |

### `memory` server

| Tool | Description |
|------|-------------|
| `embed_and_store_papers(paper_ids[])` | Generate + store embeddings ([] = all pending) |
| `semantic_search(query, top_k)` | Vector search by natural-language query |
| `find_similar_papers(paper_id, top_k)` | Papers similar to a given paper |
| `cluster_topics(min_cluster_size?, n_clusters?)` | KMeans topic clustering |
| `get_paper_feature_vector(paper_id)` | Retrieve embedding metadata |

### `investor_signal` server

| Tool | Description |
|------|-------------|
| `score_investor_relevance(paper_id)` | Score one paper (0–1) |
| `rank_papers_for_investor(query, top_k)` | Semantic + investor blended ranking |
| `explain_score(paper_id)` | Detailed feature breakdown |

---

## OCR Gating Logic

```
For each paper with investor_score >= OCR_SCORE_THRESHOLD:
    IF is_open_access AND pdf_url is available:
        1. Download PDF
        2. Convert to images (first 8 pages, 150 DPI)
        3. Call paddleocr MCP on each image
        4. Append extracted text to paper record
        5. Re-compute investor score with enriched text
    ELSE:
        Skip (log reason)
```

Default threshold: `OCR_SCORE_THRESHOLD=0.6` (set in `.env`).

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `S2_API_KEY` | _(empty)_ | Semantic Scholar API key |
| `OPENALEX_EMAIL` | example.com | Polite pool identifier |
| `OPENAI_API_KEY` | _(empty)_ | OpenAI key (for cloud embeddings) |
| `EMBEDDING_BACKEND` | `fastembed` | `fastembed` or `openai` |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Model name |
| `EMBEDDING_DIM` | `384` | Vector dimension |
| `QDRANT_URL` | _(empty)_ | Qdrant server URL (blank = in-memory) |
| `QDRANT_COLLECTION` | `papers` | Collection name |
| `DB_PATH` | `./data/papers.db` | SQLite database path |
| `OCR_SCORE_THRESHOLD` | `0.6` | Minimum score to trigger PDF OCR |
| `PDF_DOWNLOAD_DIR` | `./data/pdfs` | PDF cache directory |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `LOG_DIR` | `./logs` | Log file directory |

---

## Rate Limits & Retries

Both API clients use `tenacity` with exponential backoff:
- Up to 6 retries, starting at 2 seconds, capping at 60 seconds.
- Respects `Retry-After` headers on HTTP 429.
- Semantic Scholar: ~1 req/sec without key; ~1000 req/min with key.
- OpenAlex: 10 req/sec (polite pool).

Retry events are logged at `WARNING` level in the respective server log files.
