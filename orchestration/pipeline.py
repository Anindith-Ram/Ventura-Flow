"""End-to-end research intelligence pipeline.

Steps
-----
1. Metadata ingestion   (Semantic Scholar / OpenAlex)
2. Embedding            (fastembed / OpenAI)
3. Novelty ranking      (LLM novelty/IP/value scoring)
4. OCR gating           (PDF download → paddleocr MCP → re-score)
5. Artifact export      (JSON run report + logs)

Usage
-----
    from orchestration.pipeline import run_pipeline
    result = run_pipeline(query="RNA therapeutics", limit=20)

    # Or via CLI:
    python -m orchestration.pipeline --query "RNA therapeutics" --limit 20
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from shared.config import settings

# ── logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stderr),
        logging.FileHandler(Path(settings.log_dir) / "pipeline.log"),
    ],
)
logger = logging.getLogger("pipeline")

from shared.db import (
    finish_pipeline_run,
    get_paper,
    get_papers_by_ids,
    init_db,
    mark_embedded,
    save_pipeline_run,
    update_investor_score,
    update_ocr_text,
)
from shared.embeddings import embed_texts
from shared.models import InvestorScore, Paper, PipelineRun
from shared.vector_store import get_store


# ── step implementations ──────────────────────────────────────────────────────

def _step_ingest(
    query: str,
    limit: int,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
) -> list[str]:
    """Fetch and store metadata; return list of paper_ids."""
    from papers_mcp.semantic_scholar import SemanticScholarClient
    from papers_mcp.openalex import OpenAlexClient
    from shared.db import upsert_papers

    logger.info(
        "[Step 1] Ingesting metadata for query=%r limit=%d year_from=%s year_to=%s",
        query,
        limit,
        year_from,
        year_to,
    )
    papers: list[Paper] = []
    try:
        s2 = SemanticScholarClient()
        papers = s2.search(query, limit=limit, year_from=year_from, year_to=year_to)
        logger.info("Semantic Scholar: %d papers", len(papers))
    except Exception as exc:
        logger.warning("S2 failed: %s", exc)

    if len(papers) < limit // 2:
        try:
            oa = OpenAlexClient()
            extra = oa.search(
                query,
                limit=limit - len(papers),
                year_from=year_from,
                year_to=year_to,
            )
            seen = {p.paper_id for p in papers}
            papers.extend(p for p in extra if p.paper_id not in seen)
            logger.info("OpenAlex fallback added: %d papers", len(extra))
        except Exception as exc:
            logger.warning("OpenAlex fallback failed: %s", exc)

    papers = papers[:limit]
    upserted = upsert_papers(papers)
    logger.info("[Step 1 done] %d papers stored.", upserted)
    return [p.paper_id for p in papers]


def _step_embed(paper_ids: list[str]) -> int:
    """Generate embeddings and store in Qdrant. Returns count embedded."""
    logger.info("[Step 2] Embedding %d papers", len(paper_ids))
    papers = get_papers_by_ids(paper_ids)
    if not papers:
        logger.warning("No papers found in DB for embedding.")
        return 0

    texts = [p.text_for_embedding for p in papers]
    vectors = embed_texts(texts)
    store = get_store()

    records = [
        (
            p.paper_id,
            vec,
            {
                "paper_id": p.paper_id,
                "title": p.title,
                "abstract": p.abstract or "",
                "year": p.year,
                "venue": p.venue or "",
                "citation_count": p.citation_count,
                "is_open_access": p.is_open_access,
                "source": p.source,
                "fields_of_study": p.fields_of_study,
            },
        )
        for p, vec in zip(papers, vectors)
    ]
    store.upsert_batch(records)
    mark_embedded([p.paper_id for p in papers])
    logger.info("[Step 2 done] %d embeddings stored.", len(papers))
    return len(papers)


def _step_rank(
    paper_ids: list[str],
    top_k: int,
    vc_profile: str = "",
) -> list[InvestorScore]:
    """Compute investor scores; return top_k sorted descending."""
    from investor_signal_mcp.server import compute_investor_score

    logger.info("[Step 3] Scoring %d papers for investor relevance", len(paper_ids))
    papers = get_papers_by_ids(paper_ids)
    scores: list[InvestorScore] = []
    for paper in papers:
        s = compute_investor_score(paper, vc_profile=vc_profile)
        update_investor_score(paper.paper_id, s.total_score)
        scores.append(s)

    scores.sort(key=lambda x: x.total_score, reverse=True)
    logger.info(
        "[Step 3 done] Top score=%.3f, bottom=%.3f",
        scores[0].total_score if scores else 0,
        scores[-1].total_score if scores else 0,
    )
    # Return all scores sorted; callers apply threshold and top_k themselves
    return scores


def _download_pdf(paper: Paper) -> Optional[Path]:
    """Download open-access PDF; returns local path or None on failure."""
    if not paper.pdf_url:
        return None
    dest = Path(settings.pdf_download_dir) / f"{paper.paper_id}.pdf"
    if dest.exists():
        logger.info("PDF already cached: %s", dest)
        return dest
    try:
        import httpx

        logger.info("Downloading PDF for %s from %s", paper.paper_id, paper.pdf_url)
        with httpx.Client(timeout=60, follow_redirects=True) as client:
            resp = client.get(paper.pdf_url)
            resp.raise_for_status()
        dest.write_bytes(resp.content)
        logger.info("PDF saved: %s (%d bytes)", dest, dest.stat().st_size)
        return dest
    except Exception as exc:
        logger.warning("PDF download failed for %s: %s", paper.paper_id, exc)
        return None


def _pdf_to_images(pdf_path: Path) -> list[Path]:
    """Convert PDF pages to images using pymupdf. Returns list of image paths."""
    try:
        import fitz  # pymupdf

        img_dir = pdf_path.parent / f"{pdf_path.stem}_pages"
        img_dir.mkdir(exist_ok=True)
        doc = fitz.open(str(pdf_path))
        paths: list[Path] = []
        max_pages = settings.ocr_max_pages
        for i, page in enumerate(doc):
            if max_pages > 0 and i >= max_pages:
                break
            pix = page.get_pixmap(dpi=150)
            img_path = img_dir / f"page_{i:03d}.png"
            pix.save(str(img_path))
            paths.append(img_path)
        doc.close()
        return paths
    except Exception as exc:
        logger.warning("PDF-to-image conversion failed: %s", exc)
        return []


async def _call_paddleocr_mcp(image_path: Path) -> str:
    """Start paddleocr MCP as subprocess and call its OCR tool."""
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        server_params = StdioServerParameters(
            command=settings.paddleocr_command,
            args=["--pipeline", "OCR", "--ppocr_source", "local"],
            env={"PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True"},
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                # List available tools to find the OCR tool name.
                tools_resp = await session.list_tools()
                tool_names = [t.name for t in tools_resp.tools]
                logger.debug("PaddleOCR MCP tools: %s", tool_names)

                # Try common tool names.
                ocr_tool = next(
                    (n for n in tool_names if "ocr" in n.lower() or "predict" in n.lower()),
                    tool_names[0] if tool_names else None,
                )
                if not ocr_tool:
                    return ""

                result = await session.call_tool(
                    ocr_tool, {"input": str(image_path)}
                )
                # Extract text from result content.
                texts = []
                for block in result.content:
                    if hasattr(block, "text"):
                        texts.append(block.text)
                return "\n".join(texts)
    except Exception as exc:
        logger.warning("paddleocr MCP call failed for %s: %s", image_path, exc)
        return ""


def _run_ocr_on_paper(paper: Paper) -> Optional[str]:
    """Download PDF and OCR it; return extracted text or None."""
    pdf_path = _download_pdf(paper)
    if not pdf_path:
        return None

    image_paths = _pdf_to_images(pdf_path)
    if not image_paths:
        return None

    logger.info("OCR: processing %d pages for %s", len(image_paths), paper.paper_id)
    all_text: list[str] = []
    loop = asyncio.new_event_loop()
    try:
        for img_path in image_paths:
            text = loop.run_until_complete(_call_paddleocr_mcp(img_path))
            if text:
                all_text.append(text)
    finally:
        loop.close()

    combined = "\n\n".join(all_text)
    return combined if combined.strip() else None


def ensure_paper_full_text(paper_id: str) -> Optional[Paper]:
    """Ensure a paper has OCR text available when open-access PDF exists."""
    paper = get_paper(paper_id)
    if paper is None:
        return None
    if (paper.ocr_text or "").strip():
        return paper
    if not paper.is_open_access or not paper.pdf_url:
        return paper

    logger.info("Ensuring full text is available for %s before analysis", paper.paper_id)
    ocr_text = _run_ocr_on_paper(paper)
    if ocr_text:
        update_ocr_text(paper.paper_id, ocr_text)
        paper.ocr_text = ocr_text
        logger.info("Full text ready for %s (%d chars)", paper.paper_id, len(ocr_text))
    else:
        logger.info("Full text unavailable for %s after OCR attempt", paper.paper_id)
    return paper


def _step_ocr_gate(
    top_scores: list[InvestorScore],
    ocr_threshold: float,
) -> list[str]:
    """Run OCR on papers above threshold; returns list of paper_ids that were OCR'd."""
    ocr_triggered: list[str] = []
    papers_above = [s for s in top_scores if s.total_score >= ocr_threshold]
    logger.info(
        "[Step 4] OCR gate: threshold=%.2f; %d/%d papers qualify",
        ocr_threshold, len(papers_above), len(top_scores),
    )

    for score in papers_above:
        paper = get_paper(score.paper_id)
        if paper is None:
            continue
        if not paper.is_open_access or not paper.pdf_url:
            logger.info(
                "Skipping OCR for %s (not open-access or no PDF URL)", paper.paper_id
            )
            continue

        ocr_text = _run_ocr_on_paper(paper)
        if ocr_text:
            update_ocr_text(paper.paper_id, ocr_text)
            ocr_triggered.append(paper.paper_id)
            logger.info(
                "OCR complete for %s: %d chars extracted", paper.paper_id, len(ocr_text)
            )
        else:
            logger.info("OCR yielded no text for %s", paper.paper_id)

    logger.info("[Step 4 done] OCR completed for %d papers", len(ocr_triggered))
    return ocr_triggered


# ── public API ────────────────────────────────────────────────────────────────

def run_pipeline(
    query: str,
    limit: int = 20,
    ocr_threshold: Optional[float] = None,
    pass_threshold: Optional[float] = None,
    recent_years: Optional[int] = None,
    top_k: int = 10,
    vc_profile: str = "",
) -> PipelineRun:
    """Execute the full research intelligence pipeline.

    Args:
        query:         Research topic / keyword query.
        limit:         Number of papers to ingest.
        ocr_threshold: Investor score threshold to trigger OCR (default from env).
        pass_threshold: Minimum novelty/value score required to continue.
        recent_years:  Restrict ingestion to papers from last N years.
        top_k:         Number of papers to include in ranked output.

    Returns:
        PipelineRun summary object (also saved to DB and logs/).
    """
    init_db()
    if ocr_threshold is None:
        ocr_threshold = settings.ocr_score_threshold
    if pass_threshold is None:
        pass_threshold = settings.paper_pass_threshold
    if recent_years is not None and recent_years < 1:
        raise ValueError("recent_years must be >= 1 when provided.")

    year_from: Optional[int] = None
    year_to: Optional[int] = None
    if recent_years is not None:
        year_to = datetime.utcnow().year
        year_from = year_to - recent_years + 1

    run_id = str(uuid.uuid4())[:8]
    started_at = datetime.utcnow()
    logger.info("=== Pipeline run %s started: query=%r limit=%d ===", run_id, query, limit)
    save_pipeline_run(run_id, query, started_at.isoformat(), {})

    # Step 1: Ingest metadata.
    paper_ids = _step_ingest(query, limit, year_from=year_from, year_to=year_to)

    # Step 2: Embed.
    n_embedded = _step_embed(paper_ids)

    # Step 3: Rank by novelty / investor value. Keep all for observability; gate OCR by threshold.
    all_scores = _step_rank(paper_ids, top_k=len(paper_ids), vc_profile=vc_profile)
    passed_scores = [s for s in all_scores if s.total_score >= pass_threshold]
    # top_scores for reporting always shows top_k regardless of threshold
    top_scores = all_scores[:top_k]
    passed_ids = [s.paper_id for s in passed_scores]
    logger.info(
        "[Step 3 gate] pass_threshold=%.2f; %d/%d papers pass threshold (showing top %d regardless)",
        pass_threshold, len(passed_scores), len(all_scores), min(top_k, len(all_scores)),
    )

    # Step 4: Conditional OCR.
    ocr_triggered = _step_ocr_gate(passed_scores, ocr_threshold)

    # Step 5: Re-score OCR'd papers (if any).
    if ocr_triggered:
        logger.info("Re-scoring %d OCR'd papers", len(ocr_triggered))
        rescored_passed = _step_rank(passed_ids, top_k=len(passed_ids), vc_profile=vc_profile)
        passed_scores = [s for s in rescored_passed if s.total_score >= pass_threshold]
        top_scores = passed_scores[:top_k]

    finished_at = datetime.utcnow()

    # Save run artifacts.
    artifacts_dir = Path(settings.log_dir) / run_id
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    run_summary = {
        "run_id": run_id,
        "query": query,
        "limit": limit,
        "pass_threshold": pass_threshold,
        "recent_years": recent_years,
        "year_from": year_from,
        "year_to": year_to,
        "ocr_threshold": ocr_threshold,
        "total_papers_ingested": len(paper_ids),
        "total_papers_passed_threshold": len(passed_scores),
        "total_embedded": n_embedded,
        "top_investor_papers": [s.model_dump() for s in top_scores],
        "ocr_triggered_for": ocr_triggered,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
    }
    (artifacts_dir / "summary.json").write_text(json.dumps(run_summary, indent=2))
    finish_pipeline_run(run_id, finished_at.isoformat())

    logger.info(
        "=== Pipeline run %s done in %.1fs — %d papers, %d embedded, %d OCR'd ===",
        run_id, (finished_at - started_at).total_seconds(),
        len(paper_ids), n_embedded, len(ocr_triggered),
    )

    return PipelineRun(
        run_id=run_id,
        query=query,
        total_papers_ingested=len(paper_ids),
        total_papers_passed_threshold=len(passed_scores),
        total_embedded=n_embedded,
        top_investor_papers=top_scores,
        ocr_triggered_for=ocr_triggered,
        artifacts_dir=str(artifacts_dir),
        started_at=started_at,
        finished_at=finished_at,
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the research intelligence pipeline")
    parser.add_argument("--query", required=True, help="Research topic")
    parser.add_argument("--limit", type=int, default=20, help="Papers to ingest")
    parser.add_argument("--ocr-threshold", type=float, default=None, help="OCR score threshold (0-1)")
    parser.add_argument("--pass-threshold", type=float, default=None, help="Score threshold required to proceed (0-1)")
    parser.add_argument("--recent-years", type=int, default=None, help="Restrict ingestion to last N years")
    parser.add_argument("--top-k", type=int, default=10, help="Top papers to report")
    parser.add_argument("--vc-profile", type=str, default="", help="Investor profile to tailor triage scoring")
    args = parser.parse_args()

    result = run_pipeline(
        query=args.query,
        limit=args.limit,
        ocr_threshold=args.ocr_threshold,
        pass_threshold=args.pass_threshold,
        recent_years=args.recent_years,
        top_k=args.top_k,
        vc_profile=args.vc_profile,
    )
    print(json.dumps({
        "run_id": result.run_id,
        "query": result.query,
        "ingested": result.total_papers_ingested,
        "pass_threshold": args.pass_threshold if args.pass_threshold is not None else settings.paper_pass_threshold,
        "recent_years": args.recent_years,
        "embedded": result.total_embedded,
        "ocr_triggered": result.ocr_triggered_for,
        "top_papers": [
            {"paper_id": s.paper_id, "title": s.title, "score": s.total_score}
            for s in result.top_investor_papers
        ],
    }, indent=2))
