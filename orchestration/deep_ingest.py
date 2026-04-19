"""Deep ingestion — download PDFs for passing papers and extract full text.

Strategy: PDF → PyMuPDF text extraction (fast, no OCR). Papers without a
PDF URL get skipped; their full_text stays None and downstream agents fall
back to the abstract.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import httpx

from shared.config import settings
from shared.db import update_full_text
from shared.models import Paper

logger = logging.getLogger(__name__)


def _safe_filename(paper_id: str) -> str:
    return paper_id.replace(":", "_").replace("/", "_") + ".pdf"


def _download_pdf(url: str, dest: Path) -> bool:
    try:
        with httpx.Client(timeout=60, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
        return True
    except Exception as exc:
        logger.warning("PDF download failed (%s): %s", url, exc)
        return False


def _extract_text(pdf_path: Path) -> Optional[str]:
    try:
        import pymupdf  # type: ignore[import-not-found]
    except ImportError:
        import fitz as pymupdf  # type: ignore[no-redef]
    try:
        with pymupdf.open(pdf_path) as doc:
            pages = [page.get_text() for page in doc]
        return "\n\n".join(p for p in pages if p.strip())
    except Exception as exc:
        logger.warning("PDF parse failed (%s): %s", pdf_path, exc)
        return None


def ingest_full_text(paper: Paper) -> Optional[str]:
    """Download + extract. Returns text on success, None otherwise."""
    if not paper.pdf_url:
        return None
    dest = Path(settings.pdf_download_dir) / _safe_filename(paper.paper_id)
    if not dest.exists():
        ok = _download_pdf(paper.pdf_url, dest)
        if not ok:
            return None
    text = _extract_text(dest)
    if text:
        paper.full_text = text
        update_full_text(paper.paper_id, text)
    return text
