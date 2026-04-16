#!/usr/bin/env python3
"""End-to-end test script for the research intelligence pipeline.

What it does
------------
1. Ingests 20 papers on a sample query ("large language models code generation").
2. Embeds all ingested papers into the vector store.
3. Shows top-5 semantically similar papers to a probe query.
4. Shows top-5 investor-ranked papers.
5. Reports which papers triggered OCR and why.

Run
---
    cd /path/to/project
    uv run python scripts/test_pipeline.py

    # Optional: custom query
    uv run python scripts/test_pipeline.py --query "CRISPR cancer therapy" --limit 20
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Ensure the project root is on sys.path when run directly.
sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console
from rich.table import Table
from rich import box

console = Console()

SAMPLE_QUERY = "large language models code generation"
PROBE_QUERY = "transformer model code completion benchmark"


def _section(title: str) -> None:
    console.rule(f"[bold cyan]{title}[/]")


def main(query: str = SAMPLE_QUERY, limit: int = 20, ocr_threshold: float = 0.55) -> None:
    _section("Setup")
    from shared.config import settings
    from shared.db import init_db

    init_db()
    console.print(f"[green]DB:[/] {settings.db_path}")
    console.print(f"[green]Embedding backend:[/] {settings.embedding_backend} / {settings.embedding_model}")
    console.print(f"[green]OCR threshold:[/] {ocr_threshold}")

    # ── Step 1: Ingest metadata ───────────────────────────────────────────────
    _section(f"Step 1: Ingest metadata — query={query!r}, limit={limit}")
    t0 = time.time()
    from papers_mcp.semantic_scholar import SemanticScholarClient
    from papers_mcp.openalex import OpenAlexClient
    from shared.db import upsert_papers
    from shared.models import Paper

    papers: list[Paper] = []
    try:
        s2 = SemanticScholarClient()
        papers = s2.search(query, limit=limit)
        console.print(f"[green]Semantic Scholar:[/] {len(papers)} papers fetched")
    except Exception as exc:
        console.print(f"[yellow]S2 failed:[/] {exc} — trying OpenAlex")

    if len(papers) < limit // 2:
        try:
            oa = OpenAlexClient()
            extra = oa.search(query, limit=limit - len(papers))
            seen = {p.paper_id for p in papers}
            papers.extend(p for p in extra if p.paper_id not in seen)
            console.print(f"[green]OpenAlex fallback:[/] added {len(extra)} more")
        except Exception as exc:
            console.print(f"[yellow]OpenAlex failed:[/] {exc}")

    papers = papers[:limit]
    upsert_papers(papers)
    elapsed = time.time() - t0
    console.print(f"[bold]Ingested {len(papers)} papers[/] in {elapsed:.1f}s")

    # Sample table.
    tbl = Table("Title", "Year", "Citations", "OA", "Source", box=box.SIMPLE)
    for p in papers[:8]:
        tbl.add_row(
            p.title[:65] + "…" if len(p.title) > 65 else p.title,
            str(p.year or "?"),
            str(p.citation_count),
            "✓" if p.is_open_access else "✗",
            p.source,
        )
    console.print(tbl)

    # ── Step 2: Embed ─────────────────────────────────────────────────────────
    _section("Step 2: Embedding papers")
    t0 = time.time()
    from shared.embeddings import embed_texts
    from shared.db import mark_embedded
    from shared.vector_store import get_store

    store = get_store()
    texts = [p.text_for_embedding for p in papers]
    console.print(f"Generating {len(texts)} embeddings (model: {settings.embedding_model})…")
    vectors = embed_texts(texts)

    records = [
        (p.paper_id, vec, {
            "paper_id": p.paper_id, "title": p.title, "abstract": p.abstract or "",
            "year": p.year, "venue": p.venue or "", "citation_count": p.citation_count,
            "is_open_access": p.is_open_access, "source": p.source,
            "fields_of_study": p.fields_of_study,
        })
        for p, vec in zip(papers, vectors)
    ]
    store.upsert_batch(records)
    mark_embedded([p.paper_id for p in papers])
    console.print(f"[bold]Embedded {len(papers)} papers[/] in {time.time() - t0:.1f}s | vector dim={len(vectors[0])}")

    # ── Step 3: Top-5 similar papers ──────────────────────────────────────────
    _section(f"Step 3: Top-5 similar papers — probe={PROBE_QUERY!r}")
    from shared.embeddings import embed_single

    probe_vec = embed_single(PROBE_QUERY)
    hits = store.search(probe_vec, top_k=5)
    tbl2 = Table("Rank", "Title", "Sim Score", "Year", box=box.SIMPLE)
    for i, h in enumerate(hits, 1):
        tbl2.add_row(
            str(i),
            h.get("title", "")[:65],
            f"{h['score']:.4f}",
            str(h.get("year", "?")),
        )
    console.print(tbl2)

    # ── Step 4: Top-5 investor-ranked papers ──────────────────────────────────
    _section("Step 4: Top-5 investor-ranked papers")
    from investor_signal_mcp.server import compute_investor_score
    from shared.db import update_investor_score

    scored = []
    for paper in papers:
        s = compute_investor_score(paper)
        update_investor_score(paper.paper_id, s.total_score)
        scored.append(s)
    scored.sort(key=lambda x: x.total_score, reverse=True)

    tbl3 = Table("Rank", "Title", "Inv Score", "Year", "Signals", box=box.SIMPLE)
    for i, s in enumerate(scored[:5], 1):
        signals = "; ".join(s.top_signals[:2]) if s.top_signals else "—"
        tbl3.add_row(
            str(i),
            s.title[:55],
            f"{s.total_score:.4f}",
            str(next((p.year for p in papers if p.paper_id == s.paper_id), "?")),
            signals[:80],
        )
    console.print(tbl3)
    console.print("[dim]⚠️  NOT INVESTMENT ADVICE[/]")

    # ── Step 5: OCR gating report ─────────────────────────────────────────────
    _section(f"Step 5: OCR gate (threshold={ocr_threshold})")
    ocr_candidates = [s for s in scored if s.total_score >= ocr_threshold]
    oa_pdfs = [
        s for s in ocr_candidates
        if next((p for p in papers if p.paper_id == s.paper_id and p.is_open_access and p.pdf_url), None)
    ]
    tbl4 = Table("Paper ID (truncated)", "Score", "OA PDF?", "OCR Decision", box=box.SIMPLE)
    for s in scored[:8]:
        paper = next((p for p in papers if p.paper_id == s.paper_id), None)
        has_pdf = paper is not None and paper.is_open_access and bool(paper.pdf_url)
        decision = (
            "[green]TRIGGER OCR[/]"
            if s.total_score >= ocr_threshold and has_pdf
            else (
                "[yellow]Above threshold but no OA PDF[/]"
                if s.total_score >= ocr_threshold
                else "[dim]Below threshold — skip[/]"
            )
        )
        tbl4.add_row(s.paper_id[:24], f"{s.total_score:.4f}", "✓" if has_pdf else "✗", decision)
    console.print(tbl4)
    console.print(
        f"[bold]{len(ocr_candidates)}[/] papers above threshold; "
        f"[bold]{len(oa_pdfs)}[/] have open-access PDFs → would trigger OCR"
    )
    console.print("[dim]Note: OCR not executed in this test to avoid heavy compute.[/]")
    console.print("[dim]Run orchestration.pipeline.run_pipeline() for full OCR execution.[/]")

    # ── Summary ───────────────────────────────────────────────────────────────
    _section("Summary")
    console.print(f"  Papers ingested : [bold]{len(papers)}[/]")
    console.print(f"  Papers embedded : [bold]{len(papers)}[/]")
    console.print(f"  Vector store    : [bold]{store.count()} points[/]")
    console.print(f"  Top inv score   : [bold]{scored[0].total_score:.4f}[/] ({scored[0].title[:50]})")
    console.print(f"  OCR candidates  : [bold]{len(ocr_candidates)}[/] (score >= {ocr_threshold})")
    console.print("\n[green bold]All steps completed successfully.[/]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="End-to-end pipeline test")
    parser.add_argument("--query", default=SAMPLE_QUERY)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--ocr-threshold", type=float, default=0.55)
    args = parser.parse_args()
    main(query=args.query, limit=args.limit, ocr_threshold=args.ocr_threshold)
