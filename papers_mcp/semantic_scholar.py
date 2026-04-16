"""Semantic Scholar Graph API v1 client with retry / backoff."""

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

_BASE = "https://api.semanticscholar.org/graph/v1"

_PAPER_FIELDS = (
    "paperId,externalIds,title,abstract,authors,year,venue,"
    "citationCount,referenceCount,fieldsOfStudy,"
    "isOpenAccess,openAccessPdf,url"
)

_AUTHOR_FIELDS = "name,authorId,affiliations"


def _should_retry(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {429, 500, 502, 503, 504}
    return isinstance(exc, (httpx.TimeoutException, httpx.ConnectError))


@retry(
    wait=wait_exponential(multiplier=1, min=2, max=60),
    stop=stop_after_attempt(6),
    retry=retry_if_exception(_should_retry),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def _get(url: str, params: dict, headers: dict) -> httpx.Response:
    with httpx.Client(timeout=30) as client:
        resp = client.get(url, params=params, headers=headers)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "60"))
            logger.warning("Rate-limited by Semantic Scholar; sleeping %ds", retry_after)
            time.sleep(retry_after)
        resp.raise_for_status()
        return resp


def _headers() -> dict:
    h = {"User-Agent": "research-intelligence/0.1"}
    if settings.s2_api_key:
        h["x-api-key"] = settings.s2_api_key
    return h


def _normalise(raw: dict, source: str = "semantic_scholar") -> Optional[Paper]:
    paper_id = raw.get("paperId")
    title = raw.get("title") or ""
    if not paper_id or not title:
        return None

    ext = raw.get("externalIds") or {}
    doi = ext.get("DOI")

    abstract = raw.get("abstract")

    raw_authors = raw.get("authors") or []
    authors = [
        Author(name=a.get("name", ""), author_id=a.get("authorId"))
        for a in raw_authors
    ]

    oa_pdf = raw.get("openAccessPdf") or {}
    pdf_url = oa_pdf.get("url")

    return Paper(
        paper_id=paper_id,
        doi=doi,
        title=title,
        abstract=abstract,
        authors=authors,
        year=raw.get("year"),
        venue=raw.get("venue"),
        url=raw.get("url"),
        pdf_url=pdf_url,
        source=source,
        citation_count=raw.get("citationCount", 0) or 0,
        is_open_access=bool(raw.get("isOpenAccess", False)),
        fields_of_study=raw.get("fieldsOfStudy") or [],
    )


class SemanticScholarClient:
    """Thin synchronous wrapper around Semantic Scholar Graph API."""

    def search(
        self,
        query: str,
        limit: int = 20,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
    ) -> list[Paper]:
        """Full-text search for papers; returns normalised Paper list."""
        params: dict = {
            "query": query,
            "limit": min(limit, 100),
            "fields": _PAPER_FIELDS,
        }
        if year_from or year_to:
            lo = str(year_from) if year_from else ""
            hi = str(year_to) if year_to else ""
            params["year"] = f"{lo}-{hi}"

        resp = _get(f"{_BASE}/paper/search", params, _headers())
        data = resp.json()
        raw_papers = data.get("data") or []
        results = []
        for raw in raw_papers:
            p = _normalise(raw)
            if p:
                results.append(p)
        logger.info("SemanticScholar search '%s': %d results", query, len(results))
        return results

    def get_paper(self, paper_id_or_doi: str) -> Optional[Paper]:
        """Fetch a single paper by Semantic Scholar ID or DOI."""
        # DOIs need to be prefixed
        if paper_id_or_doi.startswith("10."):
            pid = f"DOI:{paper_id_or_doi}"
        else:
            pid = paper_id_or_doi
        try:
            resp = _get(
                f"{_BASE}/paper/{pid}",
                {"fields": _PAPER_FIELDS},
                _headers(),
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                logger.warning("Paper not found in S2: %s", paper_id_or_doi)
                return None
            raise
        return _normalise(resp.json())

    def get_papers_batch(self, ids: list[str]) -> list[Paper]:
        """Fetch up to 500 papers by ID in one batch request."""
        # S2 batch endpoint: POST /paper/batch
        if not ids:
            return []
        # Normalise DOIs
        normalised = [f"DOI:{i}" if i.startswith("10.") else i for i in ids]
        results: list[Paper] = []
        # Process in chunks of 500 (API max).
        for chunk_start in range(0, len(normalised), 500):
            chunk = normalised[chunk_start : chunk_start + 500]
            with httpx.Client(timeout=60) as client:
                resp = client.post(
                    f"{_BASE}/paper/batch",
                    params={"fields": _PAPER_FIELDS},
                    json={"ids": chunk},
                    headers=_headers(),
                )
                resp.raise_for_status()
            for raw in resp.json():
                if raw:
                    p = _normalise(raw)
                    if p:
                        results.append(p)
        return results
