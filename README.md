# Research Intelligence Pipeline

End-to-end research pipeline for sourcing papers, building semantic memory, and ranking papers by **novelty + buildability + IP/investor value** using an LLM rubric.

> **Disclaimer:** Outputs are diligence signals only and are **NOT investment advice**.

---

## Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running The System](#running-the-system)
- [How Ranking Works](#how-ranking-works)
- [Threshold Gates](#threshold-gates)
- [MCP Tool Reference](#mcp-tool-reference)
- [End-to-End Example](#end-to-end-example)
- [Troubleshooting](#troubleshooting)

---

## Overview

This project has three MCP servers plus one orchestrator:

- `papers_mcp`: ingest metadata from Semantic Scholar / OpenAlex
- `memory_mcp`: generate embeddings and semantic retrieval
- `investor_signal_mcp`: LLM-based novelty/IP/value scoring
- `orchestration/pipeline.py`: full run orchestration with threshold gates + OCR stage

The ranking system is intentionally designed to avoid pure bibliometric ranking.  
It focuses on:

- novelty vs incremental work
- practical buildability
- evidence quality
- defensibility / moat / potential IP value
- execution risk and conceptual-only penalties

---

## Architecture

```text
papers_mcp              memory_mcp               investor_signal_mcp
    |                       |                            |
    v                       v                            v
Semantic Scholar        Embeddings + Qdrant        LLM novelty/IP/value evaluator
OpenAlex                semantic retrieval         + penalties for risk/conceptuality
    |                       |                            |
    +-----------------------+----------------------------+
                            |
                       SQLite (papers.db)
                            |
                   orchestration/pipeline.py
                            |
                 optional OCR enrichment (PaddleOCR MCP)
```

---

## Project Structure

```text
shared/
  config.py
  models.py
  db.py
  embeddings.py
  vector_store.py

papers_mcp/
  server.py
  semantic_scholar.py
  openalex.py

memory_mcp/
  server.py

investor_signal_mcp/
  server.py

orchestration/
  pipeline.py

scripts/
  test_pipeline.py
```

---

## Installation

### Option A: `uv` (recommended)

```bash
cd "Project Personal"
uv sync
```

### Option B: `pip` + `requirements.txt`

```bash
cd "Project Personal"
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## Configuration

Copy and edit environment file:

```bash
cp .env.example .env
```

Important values:

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | empty | Enables LLM novelty scoring |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible endpoint |
| `OPENAI_SCORING_MODEL` | `gpt-4.1-mini` | LLM used for scoring |
| `PAPER_PASS_THRESHOLD` | `0.65` | Minimum score to proceed |
| `OCR_SCORE_THRESHOLD` | `0.6` | Minimum score to trigger OCR stage |
| `EMBEDDING_BACKEND` | `fastembed` | `fastembed` or `openai` |
| `QDRANT_URL` | empty | Empty = in-memory store |
| `DB_PATH` | `./data/papers.db` | SQLite storage |

Notes:

- If `OPENAI_API_KEY` is not set, ranking falls back to heuristic mode.
- OCR runs only for passed papers that have OA PDFs.

---

## Running The System

### Start MCP servers individually

```bash
uv run python -m papers_mcp.server
uv run python -m memory_mcp.server
uv run python -m investor_signal_mcp.server
```

### Run full orchestration pipeline

```bash
uv run python -m orchestration.pipeline \
  --query "RNA therapeutics" \
  --limit 20 \
  --pass-threshold 0.65 \
  --ocr-threshold 0.6 \
  --top-k 10
```

### Run smoke test

```bash
uv run python scripts/test_pipeline.py --query "CRISPR delivery" --limit 20
```

---

## How Ranking Works

Ranking is implemented in `investor_signal_mcp/server.py`.

For each paper, an evaluator prompt scores:

- `novelty` (25%)
- `investor_value` (23%)
- `buildability` (22%)
- `defensibility` (16%)
- `evidence_strength` (14%)

Then subtracts penalties:

- `execution_risk` (-12%)
- `conceptual_penalty` (-18%)

Final score is clamped to `0..1`.

The rubric checks include:

- Is this genuinely new or just incremental?
- Can it be built in a practical horizon?
- Is there implementation detail, not just concept?
- Is there strong evidence (benchmarks/prototypes/trials)?
- Is there credible IP/moat and investor value path?
- Are blockers (regulatory, manufacturing, dependencies) severe?

---

## Threshold Gates

Pipeline gating in `orchestration/pipeline.py`:

1. Ingest papers
2. Embed papers
3. Score all papers
4. Keep only papers with `score >= PAPER_PASS_THRESHOLD`
5. On passed papers, OCR papers with `score >= OCR_SCORE_THRESHOLD` and OA PDF
6. Re-score OCR-enriched papers
7. Output top passed papers

This ensures low-signal papers are filtered early.

---

## MCP Tool Reference

### `papers` server

- `search_papers(query, limit, year_from?, year_to?)`
- `get_paper_details(paper_id_or_doi)`
- `ingest_metadata(query, limit, filters?)`
- `ingest_by_ids(ids[])`

### `memory` server

- `embed_and_store_papers(paper_ids[])`
- `semantic_search(query, top_k)`
- `find_similar_papers(paper_id, top_k)`
- `cluster_topics(min_cluster_size?, n_clusters?)`
- `get_paper_feature_vector(paper_id)`

### `investor_signal` server

- `score_investor_relevance(paper_id)`
- `rank_papers_for_investor(query, top_k, pass_threshold?)`
- `explain_score(paper_id)`

---

## End-to-End Example

```bash
# 1) Ingest papers
uv run python -m papers_mcp.server

# 2) Embed papers
uv run python -m memory_mcp.server

# 3) Run full pipeline with strict threshold
uv run python -m orchestration.pipeline \
  --query "solid-state battery electrolytes" \
  --limit 30 \
  --pass-threshold 0.72 \
  --ocr-threshold 0.68 \
  --top-k 8
```

---

## Troubleshooting

- **Vector store empty**
  - Run embedding step first (`embed_and_store_papers([])`).
- **LLM scoring falls back to heuristic**
  - Check `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and model name.
- **No papers pass threshold**
  - Lower `PAPER_PASS_THRESHOLD` slightly (e.g. `0.65 -> 0.58`).
- **No OCR triggered**
  - Ensure papers have OA `pdf_url` and pass OCR threshold.
- **Rate-limit errors from sources**
  - Configure `S2_API_KEY` and use retries/backoff.
