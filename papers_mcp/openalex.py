"""OpenAlex client — paper search + author enrichment (h-index, works count).

OpenAlex is free and does not require an API key. Setting OPENALEX_EMAIL
puts us in the polite pool for higher rate limits.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx
from tenacity import (
    RetryCallState,
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
)
from tenacity.wait import wait_base

from shared.config import settings
from shared.models import Author, Paper

logger = logging.getLogger(__name__)

_BASE = "https://api.openalex.org"


def _should_retry(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {429, 500, 502, 503, 504}
    return isinstance(exc, (httpx.TimeoutException, httpx.ConnectError))


class _RespectRetryAfter(wait_base):
    """Tenacity wait strategy that honours the Retry-After response header.

    Falls back to exponential backoff (1 → 2 → 4 → … capped at 60s) when the
    header is absent or the exception carries no response.
    """

    def __call__(self, rs: RetryCallState) -> float:
        exc = rs.outcome.exception()
        if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
            header = exc.response.headers.get("Retry-After")
            if header:
                try:
                    return float(header)
                except ValueError:
                    pass
        # Exponential fallback: 1, 2, 4, 8, … capped at 60
        return min(2 ** (rs.attempt_number - 1), 60)


@retry(
    wait=_RespectRetryAfter(),
    stop=stop_after_attempt(5),
    retry=retry_if_exception(_should_retry),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def _get(url: str, params: dict, client: httpx.Client) -> httpx.Response:
    """Execute a single GET. Client is passed in so callers can reuse connections."""
    resp = client.get(url, params=params)
    resp.raise_for_status()
    return resp


def _reconstruct_abstract(inv_index: Optional[dict]) -> Optional[str]:
    if not inv_index:
        return None
    positions: list[tuple[int, str]] = []
    for word, locs in inv_index.items():
        for pos in locs:
            positions.append((pos, word))
    positions.sort()
    return " ".join(w for _, w in positions)


def _normalise_work(raw: dict) -> Optional[Paper]:
    work_id = raw.get("id", "")
    title = raw.get("title") or ""
    if not work_id or not title:
        return None

    paper_id = f"OA:{work_id.split('/')[-1]}"
    doi = raw.get("doi")
    if doi:
        doi = doi.replace("https://doi.org/", "")

    abstract = _reconstruct_abstract(raw.get("abstract_inverted_index"))

    authors: list[Author] = []
    for a in raw.get("authorships") or []:
        author = a.get("author") or {}
        institutions = [
            inst.get("display_name", "")
            for inst in (a.get("institutions") or [])
            if inst.get("display_name")
        ]
        authors.append(
            Author(
                name=author.get("display_name", ""),
                author_id=author.get("id"),
                affiliations=institutions,
            )
        )

    primary_loc = raw.get("primary_location") or {}
    source = primary_loc.get("source") or {}
    venue = source.get("display_name")

    best_oa = raw.get("best_oa_location") or {}
    pdf_url = best_oa.get("pdf_url")
    landing_url = primary_loc.get("landing_page_url") or raw.get("id") or ""

    fields = [
        c.get("display_name", "")
        for c in (raw.get("concepts") or [])[:5]
        if c.get("display_name")
    ]

    return Paper(
        paper_id=paper_id,
        doi=doi,
        title=title,
        abstract=abstract,
        authors=authors,
        year=raw.get("publication_year"),
        venue=venue,
        url=landing_url,
        pdf_url=pdf_url,
        source="openalex",
        citation_count=raw.get("cited_by_count", 0) or 0,
        is_open_access=bool(raw.get("open_access", {}).get("is_oa", False)),
        fields_of_study=fields,
    )


class OpenAlexClient:
    """Paper search + author metric enrichment."""

    def _params(self, extra: dict) -> dict:
        return {"mailto": settings.openalex_email, **extra}

    # ── Paper search ────────────────────────────────────────────────────────
    def search(
        self,
        query: str,
        limit: int = 20,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
    ) -> list[Paper]:
        filter_parts = [f"title_and_abstract.search:{query}"]
        if year_from:
            filter_parts.append(f"publication_year:>{year_from - 1}")
        if year_to:
            filter_parts.append(f"publication_year:<{year_to + 1}")

        params = self._params(
            {
                "filter": ",".join(filter_parts),
                "per-page": min(limit, 200),
                "select": (
                    "id,doi,title,abstract_inverted_index,authorships,"
                    "publication_year,primary_location,best_oa_location,"
                    "cited_by_count,open_access,concepts"
                ),
            }
        )
        # Each search gets its own short-lived client; parallelism is handled
        # at the asyncio layer (gather), not here.
        with httpx.Client(timeout=30) as client:
            resp = _get(f"{_BASE}/works", params, client)
        results = resp.json().get("results") or []
        papers: list[Paper] = []
        for raw in results:
            p = _normalise_work(raw)
            if p:
                papers.append(p)
        logger.info("OpenAlex '%s': %d results", query, len(papers))
        return papers

    # ── Author enrichment ───────────────────────────────────────────────────
    def enrich_authors(self, papers: list[Paper]) -> None:
        """Populate h_index, works_count, cited_by_count for each unique author.

        Batches 50 IDs per request and reuses a single persistent HTTP connection
        across all batches to avoid repeated TLS handshakes.
        """
        author_ids: list[str] = []
        for p in papers:
            for a in p.authors:
                if a.author_id:
                    aid = a.author_id.split("/")[-1]
                    author_ids.append(aid)
        if not author_ids:
            return

        author_ids = list(dict.fromkeys(author_ids))  # dedupe, preserve order
        metrics: dict[str, dict] = {}

        batch_size = 50
        # Single persistent client for all batches — one TLS handshake total.
        with httpx.Client(timeout=30) as client:
            for i in range(0, len(author_ids), batch_size):
                batch = author_ids[i: i + batch_size]
                params = self._params(
                    {
                        "filter": f"ids.openalex:{'|'.join(batch)}",
                        "per-page": batch_size,
                        "select": "id,summary_stats,works_count,cited_by_count",
                    }
                )
                try:
                    resp = _get(f"{_BASE}/authors", params, client)
                    for a in resp.json().get("results") or []:
                        aid = a["id"].split("/")[-1]
                        stats = a.get("summary_stats") or {}
                        metrics[aid] = {
                            "h_index": stats.get("h_index"),
                            "works_count": a.get("works_count"),
                            "cited_by_count": a.get("cited_by_count"),
                        }
                except Exception as exc:
                    logger.warning("Author enrichment batch failed: %s", exc)

        for p in papers:
            for a in p.authors:
                if not a.author_id:
                    continue
                aid = a.author_id.split("/")[-1]
                m = metrics.get(aid)
                if m:
                    a.h_index = m["h_index"]
                    a.works_count = m["works_count"]
                    a.cited_by_count = m["cited_by_count"]

    # ── Single-paper fetch ──────────────────────────────────────────────────
    def get_paper(self, paper_id_or_doi: str) -> Optional[Paper]:
        if paper_id_or_doi.startswith("10."):
            url = f"{_BASE}/works/https://doi.org/{paper_id_or_doi}"
        elif paper_id_or_doi.startswith("OA:"):
            url = f"{_BASE}/works/{paper_id_or_doi[3:]}"
        else:
            url = f"{_BASE}/works/{paper_id_or_doi}"
        with httpx.Client(timeout=30) as client:
            try:
                resp = _get(url, self._params({}), client)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    return None
                raise
        return _normalise_work(resp.json())
