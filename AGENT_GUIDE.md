# Agent & Developer Guide

This guide documents the current MCP workflow, novelty/IP/value scoring behavior, threshold gating, and extension points for contributors.

---

## 1) Server Startup

All servers run over stdio (JSON-RPC over stdin/stdout).

```bash
uv run python -m papers_mcp.server
uv run python -m memory_mcp.server
uv run python -m investor_signal_mcp.server
```

Logs are written to `./logs/*.log`.

---

## 2) Recommended Workflow

```text
1) ingest_metadata(query, limit)                  [papers]
2) embed_and_store_papers([])                     [memory]
3) rank_papers_for_investor(query, top_k, pass_threshold?)   [investor_signal]
4) explain_score(paper_id)                        [investor_signal]
5) optional OCR stage via orchestration pipeline  [pipeline + paddleocr]
```

One-command run:

```bash
uv run python -m orchestration.pipeline --query "..." --limit 20
```

---

## 3) Tool Contracts

### papers MCP

#### `search_papers`

```json
{ "query": "protein structure prediction", "limit": 20, "year_from": 2022 }
```

Returns metadata list (title, abstract snippet, ids, venue, OA flag, etc).

#### `ingest_metadata`

```json
{ "query": "CRISPR therapeutics", "limit": 30, "filters": "{\"year_from\": 2021}" }
```

Returns ingest counts and errors.

#### `ingest_by_ids`

```json
{ "ids": ["649def34f8be52c8b66281af98ae884c09aef38b", "10.18653/v1/2020.acl-main.463"] }
```

---

### memory MCP

#### `embed_and_store_papers`

```json
{ "paper_ids": [] }
```

Use empty list to embed all unembedded papers.

#### `semantic_search`

```json
{ "query": "attention mechanism transformers", "top_k": 5 }
```

#### `find_similar_papers`

```json
{ "paper_id": "abc123", "top_k": 10 }
```

#### `cluster_topics`

```json
{ "min_cluster_size": 3 }
```

---

### investor_signal MCP

#### `score_investor_relevance`

```json
{ "paper_id": "abc123" }
```

Example output shape:

```json
{
  "paper_id": "abc123",
  "title": "...",
  "total_score": 0.71,
  "confidence": 0.85,
  "features": {
    "novelty": 0.82,
    "investor_value": 0.74,
    "buildability": 0.69,
    "defensibility": 0.66,
    "evidence_strength": 0.73,
    "execution_risk": 0.28,
    "conceptual_penalty": 0.19
  },
  "top_signals": ["..."],
  "caveats": ["..."],
  "disclaimer": "⚠️  NOT INVESTMENT ADVICE. Scores reflect research signal patterns only."
}
```

#### `rank_papers_for_investor`

```json
{ "query": "mRNA vaccine delivery", "top_k": 5, "pass_threshold": 0.65 }
```

Example output shape:

```json
{
  "query": "...",
  "top_k": 5,
  "pass_threshold": 0.65,
  "accepted_count": 7,
  "ranked_papers": [
    {
      "paper_id": "...",
      "title": "...",
      "year": 2024,
      "novelty_value_score": 0.78,
      "passes_threshold": true,
      "top_signals": ["..."],
      "disclaimer": "⚠️  NOT INVESTMENT ADVICE. Scores reflect research signal patterns only."
    }
  ],
  "disclaimer": "⚠️  NOT INVESTMENT ADVICE."
}
```

#### `explain_score`

```json
{ "paper_id": "abc123" }
```

Returns weighted feature contributions plus penalty breakdown and pass/fail against configured threshold.

---

## 4) Scoring Design

The ranking engine in `investor_signal_mcp/server.py` is now LLM-centered.

### Core behavior

- Uses a strict rubric prompt for novelty/IP/value diligence.
- Includes feasibility checks (can it be built?) and conceptuality checks.
- Incorporates OCR text when available (`paper.ocr_text`) to enrich evidence.
- Falls back to heuristic scoring only if the local OSS LLM call is unavailable.

### Weighted score

Positive weights:

- `novelty`: 0.25
- `investor_value`: 0.23
- `buildability`: 0.22
- `defensibility`: 0.16
- `evidence_strength`: 0.14

Penalties:

- `execution_risk`: -0.12
- `conceptual_penalty`: -0.18

Total is clamped to `[0, 1]`.

---

## 5) Threshold Gating Behavior

Two thresholds are used in orchestration:

1. **Pass threshold** (`PAPER_PASS_THRESHOLD`, default `0.65`):
   - Applied immediately after scoring all ingested papers.
   - Only passed papers continue to next stages.

2. **Text enrichment threshold** (`OCR_SCORE_THRESHOLD`, default `0.6`):
   - Applied only to already-passed papers.
   - Requires OA + PDF URL to trigger direct PDF text extraction.
   - Optional OCR fallback only runs when `OCR_FALLBACK_ENABLED=true`.

Optional time filter:

3. **Recency filter** (`--recent-years`, CLI arg):
   - Restricts ingestion to papers from the last N years.
   - Example: `--recent-years 2` keeps only current + previous year.

Pipeline sequence in `orchestration/pipeline.py`:

1) ingest (optionally filtered by recent years) -> 2) embed -> 3) score all -> 4) filter by pass threshold -> 5) direct PDF text extraction gate -> 6) optional OCR fallback -> 7) re-score enriched passed papers.

---

## 6) Configuration Reference

Key vars in `.env`:

```env
OPENAI_API_KEY=
OPENAI_BASE_URL=http://localhost:11434/v1
OPENAI_SCORING_MODEL=llama3.1:8b-instruct-q4_K_M

PAPER_PASS_THRESHOLD=0.65
OCR_SCORE_THRESHOLD=0.6
OCR_FALLBACK_ENABLED=false
PDF_TEXT_MAX_PAGES=20
```

Useful CLI overrides:

```bash
uv run python -m orchestration.pipeline \
  --query "battery materials" \
  --limit 30 \
  --pass-threshold 0.55 \
  --ocr-threshold 0.50 \
  --recent-years 2
```

---

## 7) Extending The System

### Adjust scoring behavior

Edit `investor_signal_mcp/server.py`:

- `_NOVELTY_EVAL_SYSTEM_PROMPT` for rubric logic
- `_SCORE_WEIGHTS` for positive feature weights
- penalty multipliers in `compute_investor_score`

If adding a new feature:

1) Add field to `FeatureScores` (`shared/models.py`)
2) Include it in evaluator JSON schema and parsing logic
3) Update score aggregation and explanation output

### Add new paper source

1) Create `papers_mcp/new_source.py`
2) Implement `search` and `get_paper`
3) Wire fallback path in `papers_mcp/server.py`

---

## 8) Failure Modes / Debugging

- **LLM scoring unavailable**: check local model server, `OPENAI_BASE_URL`, and model name.
- **No accepted papers**: lower `PAPER_PASS_THRESHOLD`.
- **No OCR triggered**: OCR fallback is off by default; set `OCR_FALLBACK_ENABLED=true` if needed.
- **Vector store empty errors**: run embedding step before rank/search.
- **Dim mismatch after embedding model change**: rebuild vector store.

---

## 9) File Map

```text
shared/
  config.py          environment-backed settings
  models.py          Paper, FeatureScores, InvestorScore, PipelineRun
  db.py              SQLite persistence and row mapping
  embeddings.py      fastembed/openai embeddings
  vector_store.py    Qdrant wrapper

papers_mcp/
  server.py          search + ingest tools
  openalex.py

memory_mcp/
  server.py          embedding/search/clustering tools

investor_signal_mcp/
  server.py          novelty/IP/value scoring + rank/explain tools

orchestration/
  pipeline.py        end-to-end run with pass/OCR threshold gates
```
