"""Export a run's top-K papers as a single PDF memo pack."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

from shared.db import get_paper, get_triage_scores


def _styles():
    base = getSampleStyleSheet()
    base.add(ParagraphStyle(
        "H1b", parent=base["Heading1"], fontSize=18, spaceAfter=12, textColor="#111"
    ))
    base.add(ParagraphStyle(
        "H2b", parent=base["Heading2"], fontSize=13, spaceAfter=6, textColor="#222"
    ))
    base.add(ParagraphStyle(
        "Meta", parent=base["BodyText"], fontSize=9, textColor="#666", spaceAfter=4
    ))
    base.add(ParagraphStyle(
        "Body2", parent=base["BodyText"], fontSize=10, leading=14, spaceAfter=6
    ))
    return base


def _escape(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def export_run_pdf(run_id: str, artifacts_dir: Path, top_k: int = 10) -> bytes:
    """Build a PDF memo pack for the run and return it as bytes."""
    scores = get_triage_scores(run_id)[:top_k]
    if not scores:
        raise ValueError(f"No triage scores for run {run_id}")

    styles = _styles()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        leftMargin=0.7 * inch, rightMargin=0.7 * inch,
        topMargin=0.7 * inch, bottomMargin=0.7 * inch,
    )
    story = []

    story.append(Paragraph(f"Research Memo Pack — {run_id}", styles["H1b"]))
    story.append(Paragraph(f"Top {len(scores)} papers", styles["Meta"]))
    story.append(Spacer(1, 12))

    for rank, s in enumerate(scores, 1):
        paper = get_paper(s.paper_id)
        if not paper:
            continue
        story.append(Paragraph(f"#{rank} · {_escape(paper.title)}", styles["H2b"]))

        authors = ", ".join(a.name for a in paper.authors[:4])
        if len(paper.authors) > 4:
            authors += f" + {len(paper.authors) - 4} more"
        meta_line = (
            f"{authors or 'Unknown authors'} · {paper.year or '—'} · "
            f"{paper.venue or '—'} · {paper.citation_count} citations"
        )
        story.append(Paragraph(_escape(meta_line), styles["Meta"]))
        score_line = (
            f"Composite {s.composite:.0f}/100 · VC-fit {s.vc_fit:.0f} · "
            f"Novelty {s.novelty:.0f} · Credibility {s.credibility:.0f} · "
            f"Subfield: {s.subfield}"
        )
        story.append(Paragraph(_escape(score_line), styles["Meta"]))
        story.append(Paragraph(f"<i>{_escape(s.rationale)}</i>", styles["Body2"]))

        # Try to include judge memo if available
        paper_dir = artifacts_dir / paper.paper_id.replace(":", "_")
        judge_path = paper_dir / "judge_evaluation.json"
        deck_path = paper_dir / "pitch_deck.json"
        if judge_path.exists():
            try:
                ev = json.loads(judge_path.read_text())
                story.append(Paragraph("Investability", styles["H2b"]))
                story.append(Paragraph(
                    f"<b>{ev.get('investability_score', '—')}/100 · "
                    f"{ev.get('recommendation', '—')}</b>",
                    styles["Body2"],
                ))
                verdict = ev.get("one_line_verdict") or ev.get("investability_rationale", "")
                if verdict:
                    story.append(Paragraph(_escape(verdict), styles["Body2"]))
            except Exception:
                pass
        if deck_path.exists():
            try:
                deck = json.loads(deck_path.read_text())
                memo_title = deck.get("memo_title")
                tldr = deck.get("tldr") or deck.get("one_line_verdict")
                if memo_title:
                    story.append(Paragraph(_escape(memo_title), styles["H2b"]))
                if tldr:
                    story.append(Paragraph(_escape(tldr), styles["Body2"]))
            except Exception:
                pass

        story.append(Paragraph(_escape(paper.abstract or "")[:1500], styles["Body2"]))
        story.append(PageBreak())

    doc.build(story)
    return buffer.getvalue()
