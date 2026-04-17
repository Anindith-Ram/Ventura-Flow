#!/usr/bin/env python3
"""List ingested paper metadata from local SQLite DB.

Examples
--------
uv run python scripts/list_ingested.py
uv run python scripts/list_ingested.py --limit 50 --source openalex
uv run python scripts/list_ingested.py --year-from 2025 --with-abstract
uv run python scripts/list_ingested.py --as-json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

# Ensure project root import works when run directly.
sys.path.insert(0, str(Path(__file__).parent.parent))

from rich import box
from rich.console import Console
from rich.table import Table

from shared.config import settings


def _build_query(args: argparse.Namespace) -> tuple[str, list[object]]:
    where: list[str] = []
    params: list[object] = []

    if args.source:
        where.append("source = ?")
        params.append(args.source)
    if args.year_from is not None:
        where.append("year >= ?")
        params.append(args.year_from)
    if args.year_to is not None:
        where.append("year <= ?")
        params.append(args.year_to)
    if args.only_open_access:
        where.append("is_open_access = 1")
    if args.has_abstract:
        where.append("abstract IS NOT NULL AND trim(abstract) != ''")

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    query = f"""
        SELECT
            paper_id,
            title,
            abstract,
            year,
            venue,
            source,
            citation_count,
            is_open_access,
            fetched_at
        FROM papers
        {where_sql}
        ORDER BY datetime(fetched_at) DESC
        LIMIT ?
    """
    params.append(args.limit)
    return query, params


def _fetch_rows(args: argparse.Namespace) -> list[dict]:
    db_path = Path(settings.db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"DB not found at {db_path}")

    query, params = _build_query(args)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def _print_table(rows: list[dict], with_abstract: bool) -> None:
    console = Console()
    columns = ["#", "Year", "Source", "OA", "Citations", "Paper ID", "Title", "Venue", "Fetched At"]
    if with_abstract:
        columns.append("Abstract")

    table = Table(*columns, box=box.SIMPLE, show_lines=False)
    for i, row in enumerate(rows, 1):
        values = [
            str(i),
            str(row.get("year") or ""),
            str(row.get("source") or ""),
            "yes" if row.get("is_open_access") else "no",
            str(row.get("citation_count") or 0),
            str(row.get("paper_id") or "")[:24],
            str(row.get("title") or "")[:90],
            str(row.get("venue") or "")[:40],
            str(row.get("fetched_at") or ""),
        ]
        if with_abstract:
            abstract = str(row.get("abstract") or "")
            values.append(abstract[:180] + ("..." if len(abstract) > 180 else ""))
        table.add_row(*values)
    console.print(table)
    console.print(f"\nRows shown: [bold]{len(rows)}[/]")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="List ingested papers from local DB")
    parser.add_argument("--limit", type=int, default=25, help="Max rows to show (default: 25)")
    parser.add_argument(
        "--source",
        choices=["openalex"],
        default=None,
        help="Filter by source",
    )
    parser.add_argument("--year-from", type=int, default=None, help="Filter by minimum year")
    parser.add_argument("--year-to", type=int, default=None, help="Filter by maximum year")
    parser.add_argument("--only-open-access", action="store_true", help="Only open-access papers")
    parser.add_argument("--has-abstract", action="store_true", help="Only papers with non-empty abstract")
    parser.add_argument("--with-abstract", action="store_true", help="Show abstract preview column")
    parser.add_argument("--as-json", action="store_true", help="Output rows as JSON")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = _fetch_rows(args)
    if args.as_json:
        print(json.dumps(rows, indent=2))
        return
    _print_table(rows, with_abstract=args.with_abstract)


if __name__ == "__main__":
    main()
