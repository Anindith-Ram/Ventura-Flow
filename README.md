# Research Intelligence Pipeline

End-to-end pipeline that ingests scientific papers, triages them against a VC's
thesis using local LLM agents, and produces investment memos via a bull/bear
debate — all running locally on Ollama with a React GUI on top.

> **Disclaimer:** outputs are diligence signals only, **not investment advice**.

---

## What it does

1. **Plan queries** from the VC's thesis (not random keywords) — the Query
   Planner agent reasons about sectors, stage, and geography to emit tailored
   OpenAlex queries. In autonomous mode it tracks angles already covered and
   proposes fresh ones each round.
2. **Ingest metadata** from OpenAlex (author h-index / works_count enrichment
   included).
3. **Dedup** via fastembed cosine similarity on title+abstract.
4. **Agentic triage** — a Triage Agent scores every paper on
   `vc_fit / novelty / author_credibility` with a rationale. No keyword rubric.
5. **Percentile gate + diversity cap** — keep the top 10% by composite score,
   enforcing a per-subfield cap so a single topic cannot dominate the top list.
6. **Deep ingestion (PDF → text)** runs only for papers that pass the gate.
7. **Bull / bear / judge** debate on the top-K passing papers produces
   investability scores and a memo pack (PDF export).

A FastAPI backend + React frontend provide a terminal-style live dashboard,
global VC profile management, and a full run history browser.

---

## Architecture

```text
                ┌──────────────────────────────────────┐
                │  React GUI (Vite)                    │
                │   Home / Preferences / Filters       │
                │   Rankings / Past Runs / Paper View  │
                └─────────────┬────────────────────────┘
                              │ REST + WebSocket
                ┌─────────────▼────────────────────────┐
                │  gui/server.py  (FastAPI)            │
                └─────────────┬────────────────────────┘
                              │
   ┌──────────────────────────▼───────────────────────────┐
   │  orchestration/pipeline.py  +  orchestration/autonomous.py
   │                                                      │
   │  Query Planner → OpenAlex → Dedup → Triage Agent     │
   │     → Percentile + Diversity Gate → PDF Ingest       │
   │     → Bull/Bear Researcher → Analyst → Judge         │
   └──────────────────────────┬───────────────────────────┘
                              │ events
                     orchestration/events.py  (pub/sub)
                              │
                     SQLite (data/papers.db)
                     Artifacts (outputs/{run_id}/)
                     Profile (~/.research_pipeline/vc_profile.json)
```

All agents run on **Ollama** with local Q4 quantized models:

| Agent | Model |
|-------|-------|
| Planner / Triage / Researchers | `qwen3:8b` |
| Analysts | `deepseek-r1:14b` |
| Judge | `llama3.1:8b` |

---

## Project layout

```text
pipeline.py                ← top-level launcher (GUI + CLI)
shared/                    ← config, models, db, embeddings, VC profile
papers_mcp/openalex.py     ← OpenAlex client (no Semantic Scholar)
agents/
  query_planner.py         ← thesis-aware query generation
  triage_agent.py          ← agentic VC-fit / novelty / credibility scorer
  bull_researcher.py       ← + bear_researcher / bull_analyst / bear_analyst / judge_agent
orchestration/
  pipeline.py              ← PipelineRunner.run_once
  autonomous.py            ← time/paper-cap loop with exclude_angles
  dedup.py                 ← cosine-based paper dedup
  diversity.py             ← percentile + subfield cap selection
  deep_ingest.py           ← PDF → text for passing papers
  events.py                ← event bus (terminal + WS subscribers)
gui/
  server.py                ← FastAPI backend + WebSocket /ws/events
  pdf_export.py            ← memo pack generation (ReportLab)
  frontend/                ← React + Vite + TypeScript
tools/                     ← ollama + ddg search helpers
outputs/                   ← per-run artifacts
data/                      ← SQLite + downloaded PDFs
```

---

## Quick start (after cloning)

Prerequisites: [Ollama](https://ollama.com/download), [uv](https://github.com/astral-sh/uv), [Node.js](https://nodejs.org) (v18+).

```bash
# 1. Python deps
uv sync

# 2. Pull Ollama models (one-time, ~15 GB total)
ollama pull qwen3:8b
ollama pull deepseek-r1:14b
ollama pull llama3.1:8b

# 3. Build the React frontend (one-time, or after any frontend change)
cd gui/frontend
npm install
npm run build
cd ../..

# 4. Launch
uv run python pipeline.py
```

The browser opens to `http://127.0.0.1:8000`. Fill in your VC profile, then
hit **Start run**.

> `data/`, `logs/`, and `gui/frontend/dist/` are gitignored, so every new
> clone needs steps 1–3 above. Steps 1 and 3 only need re-running if
> `pyproject.toml` or frontend source files change.

Environment is optional — defaults work out of the box. See `shared/config.py`
for all knobs (`TRIAGE_TOP_PERCENTILE`, `DIVERSITY_MAX_PER_SUBFIELD`,
`AUTONOMOUS_DEFAULT_MINUTES`, etc.).

---

## Running

### GUI (recommended)

```bash
uv run python pipeline.py
```

Opens `http://127.0.0.1:8000`. Edit the VC profile, pick a template, then
**Start run** from the Home page. Events stream to the embedded terminal and
the Rankings page updates live.

### CLI (headless)

```bash
# Single round with the saved profile
uv run python pipeline.py --cli single

# Autonomous mode — runs until time-limit OR paper-cap hits
uv run python pipeline.py --cli autonomous

# GUI without opening a browser tab
uv run python pipeline.py --no-browser
```

---

## How triage works

For each paper the Triage Agent returns:

- `vc_fit` (0–100) — alignment with thesis, sectors, stage, deal-breakers
- `novelty` (0–100) — originality vs incremental
- `credibility` (0–100) — author track record (h-index works as a modifier, not
  a filter, so breakthrough papers from junior researchers still surface)
- `subfield` — used by the diversity gate
- `rationale` — one or two sentences, shown as a tooltip in the Rankings UI

Composite = weighted sum (weights normalised on save in the Filters page). The
top 10% by composite go through, with a per-subfield cap and a minimum floor
so you always get at least a few papers even when a run returns few results.

---

## Autonomous mode

Loops rounds until **either** the time limit or the paper cap is hit. Each
round:

1. Planner emits N queries, **excluding** angles covered in prior rounds.
2. Ingest → dedup → triage the new papers (already-scored papers are skipped).
3. At the end of the run, deep analysis (bull/bear/judge) runs on the overall
   top-K across every round.

Progress, time remaining, and papers-so-far stream to the Terminal.

---

## Artifacts per run

```
outputs/{run_id}/
  {paper_id_safe}/
    bull_brief.md
    bear_brief.md
    bull_thesis.md
    bear_critique.md
    judge_evaluation.json
    pitch_deck.json
```

A memo-pack PDF containing the top K evaluated papers can be exported from
the Rankings page or from `GET /api/runs/{run_id}/export.pdf?top_k=10`.

---

## Troubleshooting

- **`HTTP 404` from Ollama** — the required model isn't pulled. Run
  `ollama pull qwen3:8b` (and the other two).
- **GUI shows "frontend not built yet"** — run `npm run build` inside
  `gui/frontend/`.
- **No papers surface** — broaden the thesis, widen `year_from`, or relax the
  deal-breakers; the percentile gate is adaptive but still needs a usable
  ingest pool.
- **Run seems stuck** — the Terminal and the `/api/run/status` endpoint show
  the active stage. Bull/bear/judge takes the longest because three model
  families load sequentially.
