"""FastAPI backend for the Research Intelligence Pipeline GUI.

Serves:
  - REST endpoints for VC profile, run control, run history, paper details
  - WebSocket /ws/events for live pipeline event streaming
  - Static React build at /
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from shared.config import settings
from shared.db import get_paper, get_run, get_triage_scores, init_db, list_runs
from shared.models import PipelineEvent, RunConfig, VCProfile
from shared.vc_profile import TEMPLATES, load_profile, save_profile

from orchestration.autonomous import run_autonomous
from orchestration.events import get_bus
from orchestration.pipeline import PipelineRunner
from gui.pdf_export import export_run_pdf

logger = logging.getLogger(__name__)

app = FastAPI(title="Research Intelligence Pipeline")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()
bus = get_bus()
_runner: Optional[PipelineRunner] = None
_active_task: Optional[asyncio.Task] = None


def _get_runner() -> PipelineRunner:
    global _runner
    if _runner is None:
        _runner = PipelineRunner(bus)
    return _runner


# ── Profile endpoints ───────────────────────────────────────────────────────

@app.get("/api/profile")
def api_profile() -> dict:
    return load_profile().model_dump(mode="json")


@app.put("/api/profile")
def api_profile_save(profile: VCProfile) -> dict:
    save_profile(profile)
    return {"ok": True, "updated_at": profile.updated_at.isoformat()}


@app.get("/api/profile/templates")
def api_templates() -> dict:
    return {k: v.model_dump(mode="json") for k, v in TEMPLATES.items()}


# ── Run control ─────────────────────────────────────────────────────────────

class StartRunPayload(BaseModel):
    mode: str = "single"  # "single" | "autonomous"
    max_queries: int = 6
    papers_per_query: int = 20
    bull_bear_for_top_k: int = 5
    autonomous_time_limit_minutes: int = 60
    autonomous_paper_cap: int = 200


@app.post("/api/run/start")
async def api_run_start(payload: StartRunPayload) -> dict:
    global _active_task
    if _active_task and not _active_task.done():
        raise HTTPException(status_code=409, detail="A run is already active")

    profile = load_profile()
    config = RunConfig(
        mode=payload.mode,  # type: ignore[arg-type]
        max_queries=payload.max_queries,
        papers_per_query=payload.papers_per_query,
        bull_bear_for_top_k=payload.bull_bear_for_top_k,
        autonomous_time_limit_minutes=payload.autonomous_time_limit_minutes,
        autonomous_paper_cap=payload.autonomous_paper_cap,
    )

    runner = _get_runner()
    if config.mode == "autonomous":
        _active_task = asyncio.create_task(run_autonomous(runner, profile, config))
    else:
        _active_task = asyncio.create_task(runner.run_once(profile, config))
    return {"ok": True, "mode": config.mode}


@app.post("/api/run/cancel")
async def api_run_cancel() -> dict:
    global _active_task
    if _active_task and not _active_task.done():
        _active_task.cancel()
        return {"ok": True, "cancelled": True}
    return {"ok": True, "cancelled": False}


@app.get("/api/run/status")
def api_run_status() -> dict:
    active = bool(_active_task and not _active_task.done())
    return {"active": active}


# ── History / Results ───────────────────────────────────────────────────────

@app.get("/api/runs")
def api_runs(limit: int = 50) -> list[dict]:
    runs = list_runs(limit)
    return runs


@app.get("/api/runs/{run_id}")
def api_run(run_id: str) -> dict:
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    scores = [s.model_dump() for s in get_triage_scores(run_id)]
    return {"run": run, "scores": scores}


@app.get("/api/runs/{run_id}/paper/{paper_id}")
def api_run_paper(run_id: str, paper_id: str) -> dict:
    paper = get_paper(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="Paper not found")
    # Surface judge + pitch-deck + theses if they exist.
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    paper_dir = Path(run["artifacts_dir"]) / paper_id.replace(":", "_")
    artefacts: dict = {}
    for name in ("bull_brief.md", "bear_brief.md", "bull_thesis.md", "bear_critique.md"):
        fp = paper_dir / name
        if fp.exists():
            artefacts[name] = fp.read_text()
    for name in ("judge_evaluation.json", "pitch_deck.json"):
        fp = paper_dir / name
        if fp.exists():
            try:
                artefacts[name] = json.loads(fp.read_text())
            except Exception:
                artefacts[name] = None
    return {"paper": paper.model_dump(mode="json"), "artefacts": artefacts}


@app.get("/api/runs/{run_id}/export.pdf")
def api_export_pdf(run_id: str, top_k: int = 10):
    run = get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    try:
        pdf_bytes = export_run_pdf(run_id, Path(run["artifacts_dir"]), top_k=top_k)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="memo_pack_{run_id}.pdf"'},
    )


# ── Events history (for page refresh / late joiners) ────────────────────────

@app.get("/api/events/recent")
def api_events_recent(run_id: Optional[str] = None, limit: int = 500) -> list[dict]:
    events = bus.recent(run_id)
    return [e.model_dump(mode="json") for e in events[-limit:]]


# ── WebSocket ───────────────────────────────────────────────────────────────

@app.websocket("/ws/events")
async def ws_events(websocket: WebSocket) -> None:
    await websocket.accept()
    queue: asyncio.Queue[PipelineEvent] = asyncio.Queue(maxsize=1000)

    async def handler(event: PipelineEvent) -> None:
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            pass

    bus.subscribe(handler)

    # Replay recent events to catch the UI up
    for ev in bus.recent()[-200:]:
        try:
            await websocket.send_json(ev.model_dump(mode="json"))
        except Exception:
            break

    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event.model_dump(mode="json"))
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("WS error: %s", exc)
    finally:
        bus.unsubscribe(handler)


# ── Static React build (served at root if present) ──────────────────────────

_FRONTEND_DIST = Path(__file__).parent / "frontend" / "dist"
if _FRONTEND_DIST.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=_FRONTEND_DIST / "assets"),
        name="assets",
    )

    @app.get("/")
    def root_index():
        return FileResponse(_FRONTEND_DIST / "index.html")

    # SPA fallback — any non-API path returns index.html for client-side routing.
    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        if full_path.startswith("api") or full_path.startswith("ws"):
            raise HTTPException(status_code=404)
        target = _FRONTEND_DIST / full_path
        if target.exists() and target.is_file():
            return FileResponse(target)
        return FileResponse(_FRONTEND_DIST / "index.html")
else:
    @app.get("/")
    def root_placeholder():
        return {
            "message": "Frontend not built yet.",
            "build_instructions": "cd gui/frontend && npm install && npm run build",
        }


def run_server(host: str | None = None, port: int | None = None) -> None:
    import uvicorn
    uvicorn.run(
        app, host=host or settings.gui_host, port=port or settings.gui_port,
        log_level="info",
    )


if __name__ == "__main__":
    run_server()
