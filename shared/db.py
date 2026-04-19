"""SQLite persistence for papers, runs, and triage scores."""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator, Optional

from shared.config import settings
from shared.models import Author, Paper, RunSummary, TriageScore

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    paper_id        TEXT PRIMARY KEY,
    doi             TEXT,
    title           TEXT NOT NULL,
    abstract        TEXT,
    authors_json    TEXT,
    year            INTEGER,
    venue           TEXT,
    url             TEXT,
    pdf_url         TEXT,
    source          TEXT,
    citation_count  INTEGER DEFAULT 0,
    is_open_access  INTEGER DEFAULT 0,
    fields_of_study TEXT,
    full_text       TEXT,
    fetched_at      TEXT
);

CREATE TABLE IF NOT EXISTS triage_scores (
    run_id        TEXT,
    paper_id      TEXT,
    vc_fit        REAL,
    novelty       REAL,
    credibility   REAL,
    composite     REAL,
    rationale     TEXT,
    subfield      TEXT,
    PRIMARY KEY (run_id, paper_id)
);

CREATE TABLE IF NOT EXISTS runs (
    run_id            TEXT PRIMARY KEY,
    mode              TEXT,
    started_at        TEXT,
    finished_at       TEXT,
    queries_planned   INTEGER,
    papers_ingested   INTEGER,
    papers_passed_triage INTEGER,
    papers_deep_analyzed INTEGER,
    top_paper_ids     TEXT,
    artifacts_dir     TEXT,
    vc_profile_json   TEXT
);

CREATE TABLE IF NOT EXISTS watchlist (
    paper_id   TEXT PRIMARY KEY,
    added_at   TEXT NOT NULL,
    note       TEXT,
    source_run TEXT
);

CREATE INDEX IF NOT EXISTS idx_triage_run ON triage_scores(run_id, composite DESC);
CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_watchlist_added ON watchlist(added_at DESC);
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
    with _conn() as conn:
        conn.executescript(_SCHEMA)


# ── Papers ─────────────────────────────────────────────────────────────────

def upsert_papers(papers: list[Paper]) -> int:
    if not papers:
        return 0
    rows = [p.to_db_row() for p in papers]
    cols = ", ".join(rows[0].keys())
    placeholders = ", ".join("?" for _ in rows[0])
    sql = f"INSERT OR REPLACE INTO papers ({cols}) VALUES ({placeholders})"
    with _conn() as conn:
        conn.executemany(sql, [list(r.values()) for r in rows])
    return len(rows)


def get_paper(paper_id: str) -> Optional[Paper]:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM papers WHERE paper_id = ?", (paper_id,)).fetchone()
    return _row_to_paper(dict(row)) if row else None


def get_papers_by_ids(ids: list[str]) -> list[Paper]:
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    with _conn() as conn:
        rows = conn.execute(f"SELECT * FROM papers WHERE paper_id IN ({placeholders})", ids).fetchall()
    return [_row_to_paper(dict(r)) for r in rows]


def update_full_text(paper_id: str, full_text: str) -> None:
    with _conn() as conn:
        conn.execute("UPDATE papers SET full_text = ? WHERE paper_id = ?", (full_text, paper_id))


# ── Triage ─────────────────────────────────────────────────────────────────

def save_triage_scores(run_id: str, scores: list[TriageScore]) -> None:
    if not scores:
        return
    with _conn() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO triage_scores "
            "(run_id, paper_id, vc_fit, novelty, credibility, composite, rationale, subfield) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (run_id, s.paper_id, s.vc_fit, s.novelty, s.credibility, s.composite, s.rationale, s.subfield)
                for s in scores
            ],
        )


def get_triage_scores(run_id: str) -> list[TriageScore]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM triage_scores WHERE run_id = ? ORDER BY composite DESC", (run_id,)
        ).fetchall()
    return [TriageScore(**dict(r)) for r in rows]


# ── Runs ────────────────────────────────────────────────────────────────────

def save_run(summary: RunSummary, vc_profile_json: str) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO runs "
            "(run_id, mode, started_at, finished_at, queries_planned, papers_ingested, "
            "papers_passed_triage, papers_deep_analyzed, top_paper_ids, artifacts_dir, vc_profile_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                summary.run_id,
                summary.mode,
                summary.started_at.isoformat(),
                summary.finished_at.isoformat() if summary.finished_at else None,
                summary.queries_planned,
                summary.papers_ingested,
                summary.papers_passed_triage,
                summary.papers_deep_analyzed,
                "|".join(summary.top_paper_ids),
                summary.artifacts_dir,
                vc_profile_json,
            ),
        )


def list_runs(limit: int = 50) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_run(run_id: str) -> Optional[dict]:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def get_run_score_distribution(run_id: str, limit: int = 20) -> list[float]:
    """Top-N composite scores for this run, descending. Used for sparklines."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT composite FROM triage_scores WHERE run_id = ? "
            "ORDER BY composite DESC LIMIT ?",
            (run_id, limit),
        ).fetchall()
    return [float(r["composite"]) for r in rows]


# ── Watchlist ───────────────────────────────────────────────────────────────

def add_to_watchlist(paper_id: str, note: str | None = None, source_run: str | None = None) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO watchlist (paper_id, added_at, note, source_run) "
            "VALUES (?, ?, ?, ?)",
            (paper_id, datetime.utcnow().isoformat(), note, source_run),
        )


def remove_from_watchlist(paper_id: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM watchlist WHERE paper_id = ?", (paper_id,))


def is_watchlisted(paper_id: str) -> bool:
    with _conn() as conn:
        row = conn.execute("SELECT 1 FROM watchlist WHERE paper_id = ?", (paper_id,)).fetchone()
    return row is not None


def list_watchlist() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT w.paper_id, w.added_at, w.note, w.source_run, p.title "
            "FROM watchlist w LEFT JOIN papers p ON p.paper_id = w.paper_id "
            "ORDER BY w.added_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


# ── Row → model ─────────────────────────────────────────────────────────────

def _row_to_paper(row: dict) -> Paper:
    authors_raw = row.get("authors_json") or "[]"
    try:
        authors = [Author(**a) for a in json.loads(authors_raw)]
    except Exception:
        authors = []
    fields = [f for f in (row.get("fields_of_study") or "").split("|") if f]
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
        source=row.get("source", "openalex"),
        citation_count=row.get("citation_count", 0),
        is_open_access=bool(row.get("is_open_access", 0)),
        fields_of_study=fields,
        full_text=row.get("full_text"),
        fetched_at=datetime.fromisoformat(row["fetched_at"]) if row.get("fetched_at") else datetime.utcnow(),
    )
