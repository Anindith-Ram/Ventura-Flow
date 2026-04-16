# Agent & Developer Guide

This guide explains how to call each MCP server, how tools chain together, and design decisions for future developers extending this pipeline.

---

## 1. MCP Server Startup

All servers use **stdio transport** — they read JSON-RPC from stdin and write to stdout. OpenCode spawns them automatically when configured in `~/.config/opencode/opencode.json`.

To start manually (useful for debugging):

```bash
# In separate terminals — each server is a long-running process
uv run python -m papers_mcp.server      # port: none (stdio)
uv run python -m memory_mcp.server
uv run python -m investor_signal_mcp.server
```

Logs go to `./logs/<server>.log` and stderr. Set `LOG_LEVEL=DEBUG` for verbose output.

---

## 2. Recommended Tool Call Sequence

```
1. ingest_metadata(query, limit)            # [papers MCP]
        │
        ▼
2. embed_and_store_papers([])               # [memory MCP] — empty list = all pending
        │
        ▼
3a. semantic_search(query, top_k)          # [memory MCP] — find relevant papers
3b. cluster_topics()                        # [memory MCP] — discover themes
        │
        ▼
4. rank_papers_for_investor(query, top_k)  # [investor_signal MCP]
        │
        ▼
5. explain_score(paper_id)                 # [investor_signal MCP] — deep dive
        │
        (optional — for high-scoring OA papers)
        ▼
6. paddleocr MCP tools on PDF images       # [paddleocr MCP]
```

Or run steps 1-5 in one call:
```bash
uv run python -m orchestration.pipeline --query "..." --limit 20
```

---

## 3. Tool Inputs & Outputs

### papers MCP

#### `search_papers`
```json
// Input
{ "query": "protein structure prediction", "limit": 20, "year_from": 2022 }

// Output
{
  "count": 20,
  "papers": [
    {
      "paper_id": "abc123",
      "doi": "10.1234/...",
      "title": "...",
      "abstract": "First 300 chars...",
      "authors": ["Author A", "Author B"],
      "year": 2024,
      "venue": "Nature",
      "url": "https://...",
      "pdf_url": "https://...",
      "source": "semantic_scholar",
      "citation_count": 142,
      "is_open_access": true,
      "fields_of_study": ["Computer Science", "Biology"]
    }
  ]
}
```

#### `ingest_metadata`
```json
// Input
{ "query": "CRISPR therapeutics", "limit": 30, "filters": "{\"year_from\": 2021}" }

// Output
{ "total_fetched": 28, "total_upserted": 28, "skipped_no_abstract": 2, "errors": [] }
```

#### `ingest_by_ids`
```json
// Input
{ "ids": ["649def34f8be52c8b66281af98ae884c09aef38b", "10.18653/v1/2020.acl-main.463"] }

// Output — same as ingest_metadata
```

---

### memory MCP

#### `embed_and_store_papers`
```json
// Input — pass empty list to embed all pending papers in DB
{ "paper_ids": [] }
// or specific papers:
{ "paper_ids": ["abc123", "def456"] }

// Output
{ "embedded": 20, "total_in_store": 20, "paper_ids": ["abc123", ...] }
```

#### `semantic_search`
```json
// Input
{ "query": "attention mechanism transformers", "top_k": 5 }

// Output
{
  "query": "...",
  "top_k": 5,
  "results": [
    { "paper_id": "...", "title": "...", "year": 2023, "similarity_score": 0.9142 }
  ]
}
```

#### `cluster_topics`
```json
// Input
{ "min_cluster_size": 3 }

// Output
{
  "n_papers": 20,
  "n_clusters": 5,
  "clusters": [
    {
      "cluster_id": 0,
      "size": 7,
      "representative_paper_ids": ["abc123", "def456"],
      "top_terms": ["generation", "code", "model", "language", "training"]
    }
  ]
}
```

---

### investor_signal MCP

#### `score_investor_relevance`
```json
// Input
{ "paper_id": "abc123" }

// Output
{
  "paper_id": "abc123",
  "title": "...",
  "total_score": 0.6742,
  "confidence": 0.857,
  "features": {
    "recency": 0.9,
    "citation_velocity": 0.45,
    "domain_momentum": 0.75,
    "translational_potential": 0.625,
    "commercialization_hints": 0.5,
    "open_access_bonus": 0.8,
    "venue_prestige": 1.0
  },
  "top_signals": [
    "Published 2024 (recency=0.90)",
    "High-momentum domain keywords (score=0.75)"
  ],
  "caveats": ["Score is based on text pattern matching..."],
  "disclaimer": "⚠️  NOT INVESTMENT ADVICE."
}
```

#### `rank_papers_for_investor`
```json
// Input
{ "query": "mRNA vaccine delivery", "top_k": 5 }

// Output
{
  "query": "...",
  "ranked_papers": [
    {
      "paper_id": "...",
      "title": "...",
      "semantic_score": 0.89,
      "investor_score": 0.72,
      "blended_score": 0.822,
      "top_signals": ["Published 2024", "Benchmark results reported"]
    }
  ],
  "disclaimer": "⚠️  NOT INVESTMENT ADVICE."
}
```

---

## 4. Scoring Algorithm

The investor relevance score is a **weighted sum** of 7 transparent features:

| Feature | Weight | How it's computed |
|---------|--------|-------------------|
| `recency` | 12% | Years since publication (1.0 = current year, 0.0 = 10+ years old) |
| `citation_velocity` | 22% | Citations per year, normalised to 100 cit/yr = 1.0 |
| `domain_momentum` | 22% | Keyword hits from 40-term high-momentum list (LLMs, CRISPR, quantum, etc.) |
| `translational_potential` | 20% | Benchmark/deployment keyword hits (SOTA, clinical trial, FDA, etc.) |
| `commercialization_hints` | 12% | Startup/IP/product keyword hits |
| `open_access_bonus` | 6% | 0.8 if OA, 0.2 if not |
| `venue_prestige` | 6% | 1.0 if Nature/Science/top-tier conference, 0.3 otherwise |

Confidence = fraction of features with raw score > 0.1.

To **extend the scoring**: add terms to the lists in `investor_signal_mcp/server.py` or adjust weights in `compute_investor_score()`.

---

## 5. OCR Integration (paddleocr MCP)

The pipeline calls the existing paddleocr MCP server as a **child subprocess** using the MCP Python SDK's `stdio_client`. It:

1. Starts `paddleocr_mcp --pipeline OCR --ppocr_source local` as a subprocess.
2. Calls `session.list_tools()` to discover the OCR tool name dynamically.
3. Passes the local image path to the tool.
4. Extracts text from the response `TextContent` blocks.

The paddleocr MCP binary path is hardcoded from the existing OpenCode config:
```
/Users/naveenstalin/Desktop/Uni/Spring Semester/AI Agents/MCP for data ingestion/
    PaddleOCR/.venv-paddleocr-mcp/bin/paddleocr_mcp
```

To change it, set `PADDLEOCR_COMMAND` in `.env` (handled in `orchestration/pipeline.py`).

---

## 6. Extending the Pipeline

### Add a new paper source

1. Create `papers_mcp/new_source.py` following the pattern of `semantic_scholar.py`.
2. Implement `search(query, limit, ...) -> list[Paper]` and `get_paper(id) -> Optional[Paper]`.
3. Wire it into `papers_mcp/server.py` as a fallback.

### Add a new scoring feature

1. Add terms to `investor_signal_mcp/server.py` or create a new `_compute_X_score()` function.
2. Add the field to `FeatureScores` in `shared/models.py`.
3. Update `weights` dict in `compute_investor_score()` (ensure weights sum to 1.0).

### Switch to a different embedding model

```env
EMBEDDING_MODEL=BAAI/bge-large-en-v1.5   # 1024-dim
EMBEDDING_DIM=1024
```

Changing the model requires re-embedding all papers (delete existing Qdrant collection).

### Use OpenAI embeddings

```env
EMBEDDING_BACKEND=openai
OPENAI_API_KEY=sk-...
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIM=1536
```

### Enable persistent vector store

```bash
docker run -d -p 6333:6333 -v $(pwd)/data/qdrant:/qdrant/storage qdrant/qdrant
```
```env
QDRANT_URL=http://localhost:6333
```

---

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `ModuleNotFoundError: fastembed` | deps not installed | `uv sync` |
| `429 Too Many Requests` from S2 | No API key | Get free key at semanticscholar.org/product/api |
| `Vector store is empty` | Skipped embed step | Run `embed_and_store_papers([])` |
| `Paper not found in DB` | Not ingested | Run `ingest_metadata(query, ...)` first |
| OCR returns empty text | PaddleOCR model not cached | First run downloads model; check logs |
| `KeyError: 'embedding'` in qdrant | Dim mismatch after model change | Delete `data/qdrant` and re-embed |

---

## 8. File Map

```
shared/
  config.py          Settings from env vars
  models.py          Pydantic models (Paper, InvestorScore, ...)
  db.py              SQLite CRUD
  embeddings.py      fastembed / OpenAI embedding provider
  vector_store.py    Qdrant wrapper (in-memory or remote)

papers_mcp/
  server.py          MCP server — 4 tools
  semantic_scholar.py  S2 API client with retry
  openalex.py        OpenAlex client with retry

memory_mcp/
  server.py          MCP server — 5 tools

investor_signal_mcp/
  server.py          MCP server + scoring logic — 3 tools

orchestration/
  pipeline.py        run_pipeline() + CLI — full E2E workflow

scripts/
  test_pipeline.py   Smoke test with rich output
  run_*.sh           One-line server starters
```
