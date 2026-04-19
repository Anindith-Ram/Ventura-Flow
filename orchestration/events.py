"""Event bus — broadcasts pipeline events to WebSocket subscribers + terminal.

The orchestrator calls `emit(...)` at every meaningful step. Subscribers can
be async WebSocket handlers or simple print callbacks for CLI runs.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime
from typing import Awaitable, Callable

from shared.models import PipelineEvent

logger = logging.getLogger(__name__)

AsyncHandler = Callable[[PipelineEvent], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[AsyncHandler] = []
        self._buffer: list[PipelineEvent] = []
        self._buffer_limit = 2000  # keep recent history for late joiners

    def subscribe(self, handler: AsyncHandler) -> None:
        self._subscribers.append(handler)

    def unsubscribe(self, handler: AsyncHandler) -> None:
        if handler in self._subscribers:
            self._subscribers.remove(handler)

    def recent(self, run_id: str | None = None) -> list[PipelineEvent]:
        if run_id is None:
            return list(self._buffer)
        return [e for e in self._buffer if e.run_id == run_id]

    async def emit(self, event: PipelineEvent) -> None:
        self._buffer.append(event)
        if len(self._buffer) > self._buffer_limit:
            self._buffer = self._buffer[-self._buffer_limit :]
        _print_terminal(event)
        for h in list(self._subscribers):
            try:
                await h(event)
            except Exception as exc:
                logger.warning("Subscriber %s failed: %s", h, exc)

    def emit_sync(self, event: PipelineEvent) -> None:
        """Emit from synchronous code (wraps emit() via the running loop)."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(self.emit(event), loop)
                return
        except RuntimeError:
            pass
        asyncio.run(self.emit(event))


# ── singleton ───────────────────────────────────────────────────────────────

_bus: EventBus | None = None


def get_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus


# ── helpers ─────────────────────────────────────────────────────────────────

_LEVEL_GLYPH = {
    "info": "·",
    "warn": "!",
    "error": "✗",
    "success": "✓",
    "stage_start": "▶",
    "stage_end": "■",
}


def _print_terminal(event: PipelineEvent) -> None:
    ts = event.timestamp.strftime("%H:%M:%S")
    glyph = _LEVEL_GLYPH.get(event.level, "·")
    stage = event.stage.ljust(14)
    sys.stdout.write(f"[{ts}] {glyph} {stage} {event.message}\n")
    sys.stdout.flush()


def make_event(run_id: str, stage: str, message: str, level: str = "info", **data) -> PipelineEvent:
    return PipelineEvent(
        run_id=run_id, stage=stage, message=message, level=level,  # type: ignore[arg-type]
        data=data, timestamp=datetime.utcnow(),
    )
