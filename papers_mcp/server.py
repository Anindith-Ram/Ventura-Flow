"""papers_mcp — MCP server for paper search and metadata ingestion.

Tools
-----
search_papers       Search paper databases and return metadata.
get_paper_details   Fetch full details for one paper by ID or DOI.
ingest_metadata     Search + store papers in the local database.
ingest_by_ids       Ingest specific papers by their IDs.

Run
---
    python -m papers_mcp.server
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Optional

# ── logging setup ─────────────────────────────────────────────────────────────
from shared.config import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stderr),
        logging.FileHandler(Path(settings.log_dir) / "papers_mcp.log"),
    ],
)
logger = logging.getLogger("papers_mcp")

# ── MCP server ────────────────────────────────────────────────────────────────
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("papers", instructions=(
    "Search OpenAlex and store normalised paper metadata in local SQLite."
))

# ── database init ─────────────────────────────────────────────────────────────
from shared.db import init_db, upsert_papers, get_paper
from shared.models import IngestResult, Paper

init_db()

# ── API clients (lazy) ────────────────────────────────────────────────────────
_oa = None


def _get_oa():
    global _oa
    if _oa is None:
        from papers_mcp.openalex import OpenAlexClient
        _oa = OpenAlexClient()
    return _oa


# ── helpers ───────────────────────────────────────────────────────────────────

def _deduplicate(papers: list[Paper]) -> list[Paper]:
    seen: set[str] = set()
    unique = []
    for p in papers:
        if p.paper_id not in seen:
            seen.add(p.paper_id)
            unique.append(p)
    return unique


def _paper_to_dict(p: Paper) -> dict:
    return {
        "paper_id": p.paper_id,
        "doi": p.doi,
        "title": p.title,
        "abstract": (p.abstract[:300] + "…") if p.abstract and len(p.abstract) > 300 else p.abstract,
        "authors": [a.name for a in p.authors[:5]],
        "year": p.year,
        "venue": p.venue,
        "url": p.url,
        "pdf_url": p.pdf_url,
        "source": p.source,
        "citation_count": p.citation_count,
        "is_open_access": p.is_open_access,
        "fields_of_study": p.fields_of_study,
    }


# ── MCP tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
def search_papers(
    query: str,
    limit: int = 20,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
) -> str:
    """Search OpenAlex and return paper metadata.

    Args:
        query:     Search query string.
        limit:     Maximum number of results (default 20, max 100).
        year_from: Filter results published from this year onwards.
        year_to:   Filter results published up to this year.

    Returns:
        JSON list of paper metadata objects.
    """
    limit = min(max(1, limit), 100)
    papers: list[Paper] = []
    try:
        papers = _get_oa().search(query, limit=limit, year_from=year_from, year_to=year_to)
        logger.info("OpenAlex search returned %d papers", len(papers))
    except Exception as exc:
        logger.warning("OpenAlex search failed: %s", exc)
    papers = _deduplicate(papers)[:limit]
    return json.dumps({"count": len(papers), "papers": [_paper_to_dict(p) for p in papers]}, indent=2)


@mcp.tool()
def get_paper_details(paper_id_or_doi: str) -> str:
    """Fetch full details for a single paper by OpenAlex ID or DOI.

    Checks local database first, then fetches from upstream API.

    Args:
        paper_id_or_doi: OpenAlex ID (e.g. "OA:W2741809807") or
                         DOI (e.g. "10.18653/v1/2020.acl-main.463").

    Returns:
        JSON paper details or {"error": "not found"}.
    """
    # Check local DB first.
    cached = get_paper(paper_id_or_doi)
    if cached:
        return json.dumps({"source": "cache", "paper": _paper_to_dict(cached)}, indent=2)

    paper: Optional[Paper] = None
    try:
        paper = _get_oa().get_paper(paper_id_or_doi)
    except Exception as exc:
        logger.warning("OpenAlex get_paper failed: %s", exc)

    if paper is None:
        return json.dumps({"error": "Paper not found", "id": paper_id_or_doi})

    upsert_papers([paper])
    return json.dumps({"source": "api", "paper": _paper_to_dict(paper)}, indent=2)


@mcp.tool()
def ingest_metadata(
    query: str,
    limit: int = 20,
    filters: Optional[str] = None,
) -> str:
    """Search OpenAlex and store metadata in the local database.

    Idempotent: re-ingesting the same paper updates its record.

    Args:
        query:   Search query string.
        limit:   Maximum papers to ingest (default 20).
        filters: Optional JSON string with filter keys:
                 {"year_from": 2020, "year_to": 2024}

    Returns:
        JSON ingest statistics.
    """
    limit = min(max(1, limit), 200)
    filter_dict: dict = {}
    if filters:
        try:
            filter_dict = json.loads(filters)
        except json.JSONDecodeError:
            return json.dumps({"error": "filters must be valid JSON"})

    year_from = filter_dict.get("year_from")
    year_to = filter_dict.get("year_to")

    papers: list[Paper] = []
    errors: list[str] = []
    try:
        papers = _get_oa().search(query, limit=limit, year_from=year_from, year_to=year_to)
    except Exception as exc:
        errors.append(f"OpenAlex error: {exc}")
        logger.warning("OpenAlex ingest failed: %s", exc)
    papers = _deduplicate(papers)[:limit]
    skipped = sum(1 for p in papers if not p.abstract)
    upserted = upsert_papers(papers)

    result = IngestResult(
        total_fetched=len(papers),
        total_upserted=upserted,
        skipped_no_abstract=skipped,
        errors=errors,
    )
    logger.info("Ingested '%s': %d papers, %d upserted, %d no-abstract", query, len(papers), upserted, skipped)
    return json.dumps(result.model_dump(), indent=2)


@mcp.tool()
def ingest_by_ids(ids: list[str]) -> str:
    """Ingest specific papers by OpenAlex IDs or DOIs.

    Args:
        ids: List of paper IDs or DOIs.

    Returns:
        JSON ingest statistics.
    """
    if not ids:
        return json.dumps({"error": "ids list is empty"})

    papers: list[Paper] = []
    errors: list[str] = []

    for pid in ids:
        try:
            p = _get_oa().get_paper(pid)
            if p:
                papers.append(p)
        except Exception as exc:
            errors.append(f"OpenAlex {pid}: {exc}")

    papers = _deduplicate(papers)
    skipped = sum(1 for p in papers if not p.abstract)
    upserted = upsert_papers(papers)

    result = IngestResult(
        total_fetched=len(papers),
        total_upserted=upserted,
        skipped_no_abstract=skipped,
        errors=errors,
    )
    return json.dumps(result.model_dump(), indent=2)


# ── entrypoint ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("Starting papers MCP server (stdio)")
    mcp.run(transport="stdio")
