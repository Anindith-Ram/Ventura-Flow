"""OpenAlex API fallback client (no API key required).

Rate limit polite pool: add OPENALEX_EMAIL to env for higher limits.
Docs: https://docs.openalex.org/
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from shared.config import settings
from shared.models import Author, Paper

logger = logging.getLogger(__name__)

_BASE = "https://api.openalex.org"


def _should_retry(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {429, 500, 502, 503, 504}
    return isinstance(exc, (httpx.TimeoutException, httpx.ConnectError))


@retry(
    wait=wait_exponential(multiplier=1, min=1, max=60),
    stop=stop_after_attempt(5),
    retry=retry_if_exception(_should_retry),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def _get(url: str, params: dict) -> httpx.Response:
    with httpx.Client(timeout=30) as client:
        resp = client.get(url, params=params)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "30"))
            logger.warning("Rate-limited by OpenAlex; sleeping %ds", retry_after)
            time.sleep(retry_after)
        resp.raise_for_status()
        return resp


def _reconstruct_abstract(inv_index: Optional[dict]) -> Optional[str]:
    """Reconstruct abstract from OpenAlex inverted index format."""
    if not inv_index:
        return None
    word_positions: list[tuple[int, str]] = []
    for word, positions in inv_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort()
    return " ".join(w for _, w in word_positions)


def _normalise(raw: dict) -> Optional[Paper]:
    work_id = raw.get("id", "")
    title = raw.get("title") or ""
    if not work_id or not title:
        return None

    # Use OpenAlex ID as the paper ID (stripped to just the key).
    paper_id = f"OA:{work_id.split('/')[-1]}"
    doi = raw.get("doi")
    if doi:
        doi = doi.replace("https://doi.org/", "")

    abstract = _reconstruct_abstract(raw.get("abstract_inverted_index"))

    raw_authors = raw.get("authorships") or []
    authors = []
    for a in raw_authors:
        author = a.get("author") or {}
        institutions = [
            inst.get("display_name", "")
            for inst in (a.get("institutions") or [])
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
    landing_url = (primary_loc.get("landing_page_url") or raw.get("id") or "")

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
    """Thin synchronous wrapper around OpenAlex API."""

    def _params(self, extra: dict) -> dict:
        p = {"mailto": settings.openalex_email, **extra}
        return p

    def search(
        self,
        query: str,
        limit: int = 20,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
    ) -> list[Paper]:
        filter_parts = [f"title.search:{query}"]
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
        resp = _get(f"{_BASE}/works", params)
        results_raw = resp.json().get("results") or []
        papers = []
        for raw in results_raw:
            p = _normalise(raw)
            if p:
                papers.append(p)
        logger.info("OpenAlex search '%s': %d results", query, len(papers))
        return papers

    def get_paper(self, paper_id_or_doi: str) -> Optional[Paper]:
        if paper_id_or_doi.startswith("10."):
            url = f"{_BASE}/works/https://doi.org/{paper_id_or_doi}"
        elif paper_id_or_doi.startswith("OA:"):
            oa_id = paper_id_or_doi[3:]
            url = f"{_BASE}/works/{oa_id}"
        else:
            url = f"{_BASE}/works/{paper_id_or_doi}"
        try:
            resp = _get(url, self._params({}))
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        return _normalise(resp.json())
