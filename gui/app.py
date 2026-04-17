"""
Ventura Flow GUI — FastAPI backend.

Start:
    uv run python gui/app.py

Open: http://localhost:8000
"""
from __future__ import annotations

import json
import logging
import queue
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

app = FastAPI(title="Ventura Flow")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)
OUTPUT_DIR = ROOT / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

# run_id → {queue, status, paper, started}
_runs: dict[str, dict[str, Any]] = {}
# discover_run_id → {queue, status, papers, started}
_discover_runs: dict[str, dict[str, Any]] = {}


# ── Logging bridge (captures pipeline logger → SSE queue) ─────────────────────

class _QueueLogHandler(logging.Handler):
    def __init__(self, q: queue.Queue, event_type: str = "discover_log") -> None:
        super().__init__()
        self.q = q
        self.event_type = event_type

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.q.put({
                "type": self.event_type,
                "message": self.format(record),
                "ts": datetime.now().strftime("%H:%M:%S"),
            })
        except Exception:
            pass


# ── Paper → agent dict conversion ─────────────────────────────────────────────

def _paper_to_agent_dict(paper: Any) -> dict:
    """Convert a Paper model to the dict format agents expect.

    Includes full text (OCR) if available so the LLM reads the whole paper,
    not just the abstract.
    """
    author_names = []
    if hasattr(paper, "authors"):
        author_names = [
            (a.name if hasattr(a, "name") else str(a))
            for a in (paper.authors or [])
        ]

    full_text = (paper.ocr_text or "").strip()

    return {
        "title": paper.title,
        "abstract": paper.abstract or "",
        # If OCR text exists, expose it so researchers and analysts can cite it directly
        "full_text": full_text,
        "full_text_available": bool(full_text),
        # S2/OpenAlex-sourced papers don't have methodology/conclusions fields;
        # pass empty so agents don't hallucinate structure that isn't there.
        "methodology": "",
        "conclusions": "",
        "data_tables": "",
        "domain_tags": paper.fields_of_study or [],
        # Rich metadata the LLM uses for sourcing and context
        "authors": author_names,
        "year": paper.year,
        "venue": paper.venue or "",
        "url": paper.url or "",
        "pdf_url": paper.pdf_url or "",
        "citation_count": paper.citation_count,
        "is_open_access": paper.is_open_access,
        "source": paper.source,
        "paper_id": paper.paper_id,
    }


# ── Bull/Bear pipeline worker ─────────────────────────────────────────────────

def _run_worker(
    run_id: str,
    paper: dict,
    no_search: bool,
    agent: str,
    q: queue.Queue,
    vc_profile: str = "",
) -> None:
    from agents import bear_analyst, bear_researcher, bull_analyst, bull_researcher
    from agents.judge_agent import judge_agent
    from tools.search import batch_search

    def emit(event: dict) -> None:
        q.put(event)

    def log(msg: str) -> None:
        low = msg.lower()
        side = "bull" if "[bull" in low else "bear" if "[bear" in low else "judge" if "[judge" in low else ""
        emit({"type": "log", "message": msg, "side": side,
              "ts": datetime.now().strftime("%H:%M:%S")})

    sides = ["bull", "bear"] if agent == "both" else [agent]
    researcher_mods = {"bull": bull_researcher, "bear": bear_researcher}
    analyst_mods = {"bull": bull_analyst, "bear": bear_analyst}
    briefs: dict[str, str] = {}
    analyses: dict[str, str] = {}
    all_evidence: list[dict] = []

    # If the paper has full OCR text, log it so the analyst knows
    if paper.get("full_text_available"):
        log(f"[PIPELINE] Full paper text available ({len(paper.get('full_text',''))} chars) — agents will use complete paper.")

    try:
        # ── Stage A: Research ─────────────────────────────────────────────────
        for side in sides:
            emit({"type": "stage_start", "stage": "research", "side": side})
            rm = researcher_mods[side]
            try:
                queries = rm.generate_queries(paper, logger=log)
                emit({"type": "queries", "side": side, "queries": queries})

                if no_search:
                    log(f"[{side.upper()} RESEARCHER] Skipping web search")
                    search_results: dict = {q_: [] for q_ in queries}
                else:
                    log(f"[{side.upper()} RESEARCHER] Running {len(queries)} DuckDuckGo searches...")
                    search_results = batch_search(queries, max_results=5)
                    hits = sum(len(v) for v in search_results.values())
                    log(f"[{side.upper()} RESEARCHER] Retrieved {hits} search hits across {len(queries)} queries")

                for q_text, hits_list in search_results.items():
                    for hit in hits_list[:3]:
                        all_evidence.append({
                            "question": q_text,
                            "tool": f"DuckDuckGo ({side})",
                            "result": f"{hit.get('title','')}: {hit.get('snippet','')}",
                            "url": hit.get("url", ""),
                        })

                brief = rm.synthesize_brief(paper, search_results, logger=log)
                briefs[side] = brief
                (OUTPUT_DIR / f"{run_id}_{side}_brief.md").write_text(brief)
                emit({"type": "stage_complete", "stage": "research", "side": side, "content": brief})
            except Exception:
                tb = traceback.format_exc()
                log(f"[{side.upper()} RESEARCHER] ERROR:\n{tb}")
                emit({"type": "stage_error", "stage": "research", "side": side, "message": tb})

        # ── Stage B: Analysis ─────────────────────────────────────────────────
        for side in [s for s in sides if s in briefs]:
            emit({"type": "stage_start", "stage": "analysis", "side": side})
            am = analyst_mods[side]
            try:
                output = am.run(paper, briefs[side], logger=log)
                analyses[side] = output
                ext = "thesis" if side == "bull" else "critique"
                (OUTPUT_DIR / f"{run_id}_{side}_{ext}.md").write_text(output)
                emit({"type": "stage_complete", "stage": "analysis", "side": side, "content": output})
            except Exception:
                tb = traceback.format_exc()
                log(f"[{side.upper()} ANALYST] ERROR:\n{tb}")
                emit({"type": "stage_error", "stage": "analysis", "side": side, "message": tb})

        # ── Stage C: Judge ────────────────────────────────────────────────────
        if "bull" in analyses and "bear" in analyses:
            emit({"type": "stage_start", "stage": "judge", "side": "both"})
            log("[JUDGE] Pass 1 — Multi-dimensional investability evaluation (llama3.1:8b)...")
            state = {
                "title": paper.get("title", ""),
                "source_type": "research_paper",
                "abstract": paper.get("abstract", ""),
                "authors": paper.get("authors", []),
                "institution": paper.get("venue", ""),
                "bull_thesis": {"content": analyses["bull"]},
                "bear_thesis": {"content": analyses["bear"]},
                "evidence": all_evidence,
                "correction_guidance": "",
                "graph_context": (
                    f"VC Profile: {vc_profile}" if vc_profile
                    else "No VC profile specified."
                ),
            }
            try:
                result_state = judge_agent(state)
                judge_eval = result_state.get("judge_evaluation", {})
                pitch_deck = result_state.get("pitch_deck", {})
                (OUTPUT_DIR / f"{run_id}_judge_evaluation.json").write_text(
                    json.dumps(judge_eval, indent=2))
                (OUTPUT_DIR / f"{run_id}_pitch_deck.json").write_text(
                    json.dumps(pitch_deck, indent=2))
                score = judge_eval.get("investability_score", "?")
                rec = judge_eval.get("recommendation", "?")
                log(f"[JUDGE] Done — Score: {score}/100 | Rec: {rec}")
                emit({"type": "stage_complete", "stage": "judge", "side": "both",
                      "judge_eval": judge_eval, "pitch_deck": pitch_deck})
            except Exception:
                tb = traceback.format_exc()
                log(f"[JUDGE] ERROR:\n{tb}")
                emit({"type": "stage_error", "stage": "judge", "side": "both", "message": tb})

        _runs[run_id]["status"] = "complete"
        emit({"type": "complete", "run_id": run_id})

    except Exception:
        tb = traceback.format_exc()
        _runs[run_id]["status"] = "error"
        emit({"type": "error", "message": tb})


# ── Discovery pipeline worker ─────────────────────────────────────────────────

def _discover_worker(
    run_id: str,
    query: str,
    limit: int,
    pass_threshold: float,
    recent_years: Optional[int],
    top_k: int,
    vc_profile: str,
    q: queue.Queue,
) -> None:
    from orchestration.pipeline import _step_embed, _step_ingest, _step_rank
    from shared.db import get_paper, init_db

    def emit(event: dict) -> None:
        q.put(event)

    handler = _QueueLogHandler(q, event_type="discover_log")
    handler.setFormatter(logging.Formatter("%(message)s"))
    pl = logging.getLogger("pipeline")
    pl.addHandler(handler)

    try:
        init_db()

        year_from = year_to = None
        if recent_years:
            year_to = datetime.now().year
            year_from = year_to - recent_years + 1

        # Step 1: Ingest
        emit({"type": "discover_step", "step": "ingest", "status": "running",
              "label": f"Fetching papers from Semantic Scholar / OpenAlex..."})
        paper_ids = _step_ingest(query, limit, year_from=year_from, year_to=year_to)
        emit({"type": "discover_step", "step": "ingest", "status": "complete",
              "count": len(paper_ids), "label": f"Fetched {len(paper_ids)} papers"})

        if not paper_ids:
            emit({"type": "error",
                  "message": "No papers found. Try a broader query or remove the year filter."})
            return

        # Step 2: Embed
        emit({"type": "discover_step", "step": "embed", "status": "running",
              "label": "Generating semantic embeddings..."})
        n_embedded = _step_embed(paper_ids)
        emit({"type": "discover_step", "step": "embed", "status": "complete",
              "count": n_embedded, "label": f"Embedded {n_embedded} papers"})

        # Step 3: Score & rank
        emit({"type": "discover_step", "step": "rank", "status": "running",
              "label": f"Scoring papers for VC relevance (threshold {pass_threshold})..."})
        all_scores = _step_rank(
            paper_ids,
            top_k=len(paper_ids),
            vc_profile=vc_profile,
        )
        passed = [s for s in all_scores if s.total_score >= pass_threshold]
        top = passed[:top_k]
        emit({"type": "discover_step", "step": "rank", "status": "complete",
              "count": len(top),
              "label": f"{len(top)} papers passed threshold of {pass_threshold} (of {len(all_scores)} scored)"})

        # Build output cards
        papers_out = []
        for score in top:
            paper = get_paper(score.paper_id)
            if not paper:
                continue
            papers_out.append({
                "paper_id": score.paper_id,
                "title": score.title,
                "score": round(score.total_score, 3),
                "confidence": round(score.confidence, 3),
                "features": score.features.model_dump(),
                "top_signals": score.top_signals[:3],
                "caveats": score.caveats[:2],
                "year": paper.year,
                "venue": paper.venue,
                "url": paper.url,
                "citation_count": paper.citation_count,
                "fields_of_study": (paper.fields_of_study or [])[:4],
                "is_open_access": paper.is_open_access,
                "abstract": (paper.abstract or "")[:500],
                "has_full_text": bool(paper.ocr_text),
            })

        _discover_runs[run_id]["status"] = "complete"
        _discover_runs[run_id]["papers"] = papers_out
        emit({"type": "discover_complete",
              "papers": papers_out,
              "total_ingested": len(paper_ids),
              "passed": len(passed),
              "run_id": run_id})

    except Exception:
        _discover_runs[run_id]["status"] = "error"
        emit({"type": "error", "message": traceback.format_exc()})
    finally:
        pl.removeHandler(handler)


# ── SSE helper ────────────────────────────────────────────────────────────────

def _sse_generator(q: queue.Queue, terminal_types: tuple = ("complete", "error")):
    """Async generator that polls a thread queue and yields SSE data frames."""
    import asyncio

    async def gen():
        while True:
            try:
                event = q.get_nowait()
            except queue.Empty:
                yield ": keepalive\n\n"
                await asyncio.sleep(0.15)
                continue
            yield f"data: {json.dumps(event)}\n\n"
            if event.get("type") in terminal_types:
                break

    return gen()


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse(content=(STATIC_DIR / "index.html").read_text())


# ── Bull/Bear pipeline ────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    paper: dict
    no_search: bool = False
    agent: str = "both"
    vc_profile: str = ""


@app.post("/api/run")
async def start_run(req: RunRequest) -> dict:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    q: queue.Queue = queue.Queue()
    _runs[run_id] = {"queue": q, "status": "running",
                     "paper": req.paper, "started": datetime.now().isoformat()}
    threading.Thread(
        target=_run_worker,
        args=(run_id, req.paper, req.no_search, req.agent, q, req.vc_profile),
        daemon=True,
    ).start()
    return {"run_id": run_id}


@app.get("/api/stream/{run_id}")
async def stream_run(run_id: str) -> StreamingResponse:
    if run_id not in _runs:
        raise HTTPException(status_code=404, detail="Run not found")
    return StreamingResponse(
        _sse_generator(_runs[run_id]["queue"]),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/runs")
async def list_runs() -> list:
    return sorted(
        [{"run_id": rid, "status": r["status"], "started": r["started"],
          "title": r.get("paper", {}).get("title", "Unknown")[:60]}
         for rid, r in _runs.items()],
        key=lambda x: x["run_id"], reverse=True,
    )


@app.get("/api/outputs/{run_id}")
async def get_run_outputs(run_id: str) -> dict:
    if run_id not in _runs:
        raise HTTPException(status_code=404)
    out: dict[str, Any] = {}
    for suffix, key in [
        ("_bull_brief.md", "bull_brief"), ("_bear_brief.md", "bear_brief"),
        ("_bull_thesis.md", "bull_thesis"), ("_bear_critique.md", "bear_critique"),
        ("_judge_evaluation.json", "judge_eval"), ("_pitch_deck.json", "pitch_deck"),
    ]:
        p = OUTPUT_DIR / f"{run_id}{suffix}"
        if p.exists():
            text = p.read_text()
            out[key] = json.loads(text) if suffix.endswith(".json") else text
    return out


# ── Discovery pipeline ────────────────────────────────────────────────────────

class DiscoverRequest(BaseModel):
    query: str
    limit: int = 20
    pass_threshold: float = 0.55
    recent_years: Optional[int] = None
    top_k: int = 10
    vc_profile: str = ""


@app.post("/api/discover")
async def start_discover(req: DiscoverRequest) -> dict:
    run_id = f"disc_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    q: queue.Queue = queue.Queue()
    _discover_runs[run_id] = {"queue": q, "status": "running",
                              "papers": [], "started": datetime.now().isoformat()}
    threading.Thread(
        target=_discover_worker,
        args=(run_id, req.query, req.limit, req.pass_threshold,
              req.recent_years, req.top_k, req.vc_profile, q),
        daemon=True,
    ).start()
    return {"run_id": run_id}


@app.get("/api/discover/stream/{run_id}")
async def stream_discover(run_id: str) -> StreamingResponse:
    if run_id not in _discover_runs:
        raise HTTPException(status_code=404, detail="Discover run not found")
    return StreamingResponse(
        _sse_generator(_discover_runs[run_id]["queue"],
                       terminal_types=("discover_complete", "error")),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Paper fetch (for analysis from discovery results) ─────────────────────────

@app.get("/api/paper/{paper_id}")
async def get_paper_for_analysis(paper_id: str) -> dict:
    """Return a paper from the DB as the rich dict format the agents expect."""
    from orchestration.pipeline import ensure_paper_full_text
    from shared.db import get_paper, init_db
    init_db()
    paper = ensure_paper_full_text(paper_id)
    if paper is None:
        paper = get_paper(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found in local DB.")
    return _paper_to_agent_dict(paper)


# ── Sample ────────────────────────────────────────────────────────────────────

@app.get("/api/sample")
async def get_sample() -> dict:
    path = ROOT / "sample_input.json"
    if not path.exists():
        raise HTTPException(status_code=404)
    return json.loads(path.read_text())


if __name__ == "__main__":
    import uvicorn
    print("Starting Ventura Flow GUI at http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
