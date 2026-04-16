"""SQLite persistence layer for structured paper metadata."""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from shared.config import settings
from shared.models import Author, Paper

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    paper_id        TEXT PRIMARY KEY,
    doi             TEXT,
    title           TEXT NOT NULL,
    abstract        TEXT,
    authors         TEXT,           -- pipe-separated names
    year            INTEGER,
    venue           TEXT,
    url             TEXT,
    pdf_url         TEXT,
    source          TEXT,
    citation_count  INTEGER DEFAULT 0,
    is_open_access  INTEGER DEFAULT 0,
    fields_of_study TEXT,           -- pipe-separated
    fetched_at      TEXT,
    ocr_text        TEXT,           -- filled after OCR
    investor_score  REAL,           -- cached score
    embedded        INTEGER DEFAULT 0  -- 1 = has embedding in vector DB
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id      TEXT PRIMARY KEY,
    query       TEXT,
    started_at  TEXT,
    finished_at TEXT,
    metadata    TEXT    -- JSON blob
);
"""


@contextmanager
def _conn() -> Generator[sqlite3.Connection, None, None]:
    db_path = Path(settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Create tables if they don't exist."""
    with _conn() as conn:
        conn.executescript(_SCHEMA)
    logger.debug("Database initialised at %s", settings.db_path)


def upsert_paper(paper: Paper) -> None:
    """Insert or replace a paper record (idempotent)."""
    row = paper.to_db_row()
    cols = ", ".join(row.keys())
    placeholders = ", ".join("?" for _ in row)
    sql = f"INSERT OR REPLACE INTO papers ({cols}) VALUES ({placeholders})"
    with _conn() as conn:
        conn.execute(sql, list(row.values()))


def upsert_papers(papers: list[Paper]) -> int:
    """Bulk upsert; returns count inserted/replaced."""
    if not papers:
        return 0
    sql_template = None
    rows_batch: list[list] = []
    for paper in papers:
        row = paper.to_db_row()
        if sql_template is None:
            cols = ", ".join(row.keys())
            placeholders = ", ".join("?" for _ in row)
            sql_template = f"INSERT OR REPLACE INTO papers ({cols}) VALUES ({placeholders})"
        rows_batch.append(list(row.values()))
    with _conn() as conn:
        conn.executemany(sql_template, rows_batch)  # type: ignore[arg-type]
    return len(rows_batch)


def get_paper(paper_id: str) -> Optional[Paper]:
    """Fetch a paper by its ID; returns None if not found."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM papers WHERE paper_id = ?", (paper_id,)
        ).fetchone()
    if row is None:
        return None
    return _row_to_paper(dict(row))


def get_papers_by_ids(ids: list[str]) -> list[Paper]:
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    with _conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM papers WHERE paper_id IN ({placeholders})", ids
        ).fetchall()
    return [_row_to_paper(dict(r)) for r in rows]


def list_papers(limit: int = 200, offset: int = 0) -> list[Paper]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM papers ORDER BY year DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return [_row_to_paper(dict(r)) for r in rows]


def list_unembedded_papers(limit: int = 500) -> list[Paper]:
    """Return papers that don't yet have an embedding in the vector DB."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM papers WHERE embedded = 0 ORDER BY fetched_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_row_to_paper(dict(r)) for r in rows]


def mark_embedded(paper_ids: list[str]) -> None:
    if not paper_ids:
        return
    placeholders = ",".join("?" for _ in paper_ids)
    with _conn() as conn:
        conn.execute(
            f"UPDATE papers SET embedded = 1 WHERE paper_id IN ({placeholders})",
            paper_ids,
        )


def update_ocr_text(paper_id: str, ocr_text: str) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE papers SET ocr_text = ? WHERE paper_id = ?",
            (ocr_text, paper_id),
        )


def update_investor_score(paper_id: str, score: float) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE papers SET investor_score = ? WHERE paper_id = ?",
            (score, paper_id),
        )


def paper_exists(paper_id: str) -> bool:
    with _conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM papers WHERE paper_id = ?", (paper_id,)
        ).fetchone()
    return row is not None


def save_pipeline_run(run_id: str, query: str, started_at: str, metadata: dict) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO pipeline_runs (run_id, query, started_at, metadata) "
            "VALUES (?, ?, ?, ?)",
            (run_id, query, started_at, json.dumps(metadata)),
        )


def finish_pipeline_run(run_id: str, finished_at: str) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE pipeline_runs SET finished_at = ? WHERE run_id = ?",
            (finished_at, run_id),
        )


# ── helpers ──────────────────────────────────────────────────────────────────

def _row_to_paper(row: dict) -> Paper:
    authors = [Author(name=n) for n in (row.get("authors") or "").split("|") if n]
    fields = [f for f in (row.get("fields_of_study") or "").split("|") if f]
    from datetime import datetime

    return Paper(
        paper_id=row["paper_id"],
        doi=row.get("doi"),
        title=row["title"],
        abstract=row.get("abstract"),
        authors=authors,
        year=row.get("year"),
        venue=row.get("venue"),
        url=row.get("url"),
        pdf_url=row.get("pdf_url"),
        source=row.get("source", "unknown"),
        citation_count=row.get("citation_count", 0),
        is_open_access=bool(row.get("is_open_access", 0)),
        fields_of_study=fields,
        fetched_at=datetime.fromisoformat(row["fetched_at"]) if row.get("fetched_at") else datetime.utcnow(),
    )
