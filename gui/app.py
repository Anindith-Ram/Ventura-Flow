"""
Ventura Flow GUI — FastAPI backend.

Start:
    uv run python gui/app.py
    # or: python gui/app.py

Open: http://localhost:8000
"""
from __future__ import annotations

import json
import queue
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI(title="Ventura Flow")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)
OUTPUT_DIR = ROOT / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

# run_id -> {"queue": queue.Queue, "status": str, "paper": dict, "started": str}
_runs: dict[str, dict[str, Any]] = {}


# ── Worker ─────────────────────────────────────────────────────────────────────

def _run_worker(run_id: str, paper: dict, no_search: bool, agent: str, q: queue.Queue) -> None:
    from agents import bear_analyst, bear_researcher, bull_analyst, bull_researcher
    from agents.judge_agent import judge_agent
    from tools.search import batch_search

    def emit(event: dict) -> None:
        q.put(event)

    def log(msg: str) -> None:
        side = ""
        low = msg.lower()
        if "[bull" in low:
            side = "bull"
        elif "[bear" in low:
            side = "bear"
        elif "[judge" in low:
            side = "judge"
        emit({"type": "log", "message": msg, "side": side,
              "ts": datetime.now().strftime("%H:%M:%S")})

    sides = ["bull", "bear"] if agent == "both" else [agent]
    researcher_mods = {"bull": bull_researcher, "bear": bear_researcher}
    analyst_mods = {"bull": bull_analyst, "bear": bear_analyst}
    briefs: dict[str, str] = {}
    analyses: dict[str, str] = {}
    all_evidence: list[dict] = []

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
                    log(f"[{side.upper()} RESEARCHER] Retrieved {hits} hits")

                for q_text, hits_list in search_results.items():
                    for hit in hits_list[:2]:
                        all_evidence.append({
                            "question": q_text,
                            "tool": f"DuckDuckGo ({side})",
                            "result": f"{hit.get('title','')}: {hit.get('snippet','')}"
                        })

                brief = rm.synthesize_brief(paper, search_results, logger=log)
                briefs[side] = brief
                (OUTPUT_DIR / f"{run_id}_{side}_brief.md").write_text(brief)
                emit({"type": "stage_complete", "stage": "research", "side": side,
                      "content": brief})
            except Exception:
                tb = traceback.format_exc()
                log(f"[{side.upper()} RESEARCHER] ERROR:\n{tb}")
                emit({"type": "stage_error", "stage": "research", "side": side,
                      "message": tb})

        # ── Stage B: Analysis ─────────────────────────────────────────────────
        for side in [s for s in sides if s in briefs]:
            emit({"type": "stage_start", "stage": "analysis", "side": side})
            am = analyst_mods[side]
            try:
                output = am.run(paper, briefs[side], logger=log)
                analyses[side] = output
                ext = "thesis" if side == "bull" else "critique"
                (OUTPUT_DIR / f"{run_id}_{side}_{ext}.md").write_text(output)
                emit({"type": "stage_complete", "stage": "analysis", "side": side,
                      "content": output})
            except Exception:
                tb = traceback.format_exc()
                log(f"[{side.upper()} ANALYST] ERROR:\n{tb}")
                emit({"type": "stage_error", "stage": "analysis", "side": side,
                      "message": tb})

        # ── Stage C: Judge ────────────────────────────────────────────────────
        if "bull" in analyses and "bear" in analyses:
            emit({"type": "stage_start", "stage": "judge", "side": "both"})
            log("[JUDGE] Pass 1 — Investability evaluation (llama3.1:8b)...")
            state = {
                "title": paper.get("title", ""),
                "source_type": "research_paper",
                "abstract": paper.get("abstract", ""),
                "authors": paper.get("authors", []),
                "institution": paper.get("institution", ""),
                "bull_thesis": {"content": analyses["bull"]},
                "bear_thesis": {"content": analyses["bear"]},
                "evidence": all_evidence,
                "correction_guidance": "",
                "graph_context": "None available",
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
                emit({"type": "stage_error", "stage": "judge", "side": "both",
                      "message": tb})

        _runs[run_id]["status"] = "complete"
        emit({"type": "complete", "run_id": run_id})

    except Exception:
        tb = traceback.format_exc()
        _runs[run_id]["status"] = "error"
        emit({"type": "error", "message": tb})


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    html = (STATIC_DIR / "index.html").read_text()
    return HTMLResponse(content=html)


class RunRequest(BaseModel):
    paper: dict
    no_search: bool = False
    agent: str = "both"


@app.post("/api/run")
async def start_run(req: RunRequest) -> dict:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    q: queue.Queue = queue.Queue()
    _runs[run_id] = {
        "queue": q,
        "status": "running",
        "paper": req.paper,
        "started": datetime.now().isoformat(),
    }
    t = threading.Thread(
        target=_run_worker,
        args=(run_id, req.paper, req.no_search, req.agent, q),
        daemon=True,
    )
    t.start()
    return {"run_id": run_id}


@app.get("/api/stream/{run_id}")
async def stream_run(run_id: str) -> StreamingResponse:
    if run_id not in _runs:
        raise HTTPException(status_code=404, detail="Run not found")
    q = _runs[run_id]["queue"]

    async def generate():
        import asyncio
        while True:
            try:
                event = q.get_nowait()
            except queue.Empty:
                yield ": keepalive\n\n"
                await asyncio.sleep(0.15)
                continue
            yield f"data: {json.dumps(event)}\n\n"
            if event.get("type") in ("complete", "error"):
                break

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/runs")
async def list_runs() -> list:
    result = []
    for run_id, run in _runs.items():
        result.append({
            "run_id": run_id,
            "status": run["status"],
            "started": run["started"],
            "title": run.get("paper", {}).get("title", "Unknown")[:60],
        })
    return sorted(result, key=lambda x: x["run_id"], reverse=True)


@app.get("/api/sample")
async def get_sample() -> dict:
    path = ROOT / "sample_input.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="sample_input.json not found")
    return json.loads(path.read_text())


@app.get("/api/outputs/{run_id}")
async def get_run_outputs(run_id: str) -> dict:
    """Return all saved output files for a run as a dict of {key: content}."""
    if run_id not in _runs:
        raise HTTPException(status_code=404)
    out: dict[str, Any] = {}
    for suffix, key in [
        ("_bull_brief.md", "bull_brief"),
        ("_bear_brief.md", "bear_brief"),
        ("_bull_thesis.md", "bull_thesis"),
        ("_bear_critique.md", "bear_critique"),
        ("_judge_evaluation.json", "judge_eval"),
        ("_pitch_deck.json", "pitch_deck"),
    ]:
        p = OUTPUT_DIR / f"{run_id}{suffix}"
        if p.exists():
            text = p.read_text()
            out[key] = json.loads(text) if suffix.endswith(".json") else text
    return out


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
