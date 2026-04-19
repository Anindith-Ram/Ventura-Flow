"""Export a run's top-K papers as a styled PDF memo pack matching the Ventura Flow UI."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from shared.db import get_paper, get_run, get_triage_scores

# ── Palette (mirrors styles.css) ────────────────────────────────────────────

CORAL       = colors.HexColor("#c96442")
CORAL_BG    = colors.HexColor("#fbe9df")
CORAL_DARK  = colors.HexColor("#a84f31")
SEAWEED     = colors.HexColor("#3d5c3a")
SEAWEED_MID = colors.HexColor("#5a7a4a")
ARTICHOKE   = colors.HexColor("#8ba373")
ARTICHOKE_BG = colors.HexColor("#e8ede0")
SUN         = colors.HexColor("#d9a441")
BERRY       = colors.HexColor("#a8394b")
CREAM       = colors.HexColor("#faf9f5")
PANEL       = colors.HexColor("#f4f2ec")
LINE        = colors.HexColor("#e8e5db")
TEXT        = colors.HexColor("#1f1e1c")
TEXT_SOFT   = colors.HexColor("#3a3833")
MUTED       = colors.HexColor("#6b6860")
MUTED_2     = colors.HexColor("#8f8a7e")


def _score_color(v: float) -> colors.Color:
    if v >= 70:
        return SEAWEED
    if v >= 45:
        return SUN
    return BERRY


def _esc(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _styles() -> Any:
    s = getSampleStyleSheet()

    def add(name, **kw):
        s.add(ParagraphStyle(name, **kw))

    add("VFTitle",
        fontName="Helvetica-Bold", fontSize=22, leading=28,
        textColor=TEXT, spaceAfter=4)
    add("VFSubtitle",
        fontName="Helvetica", fontSize=11, leading=16,
        textColor=MUTED, spaceAfter=2)
    add("VFSection",
        fontName="Helvetica-Bold", fontSize=13, leading=18,
        textColor=SEAWEED, spaceBefore=14, spaceAfter=6)
    add("VFPaperTitle",
        fontName="Helvetica-Bold", fontSize=14, leading=19,
        textColor=TEXT, spaceAfter=4)
    add("VFMeta",
        fontName="Helvetica", fontSize=9, leading=13,
        textColor=MUTED, spaceAfter=3)
    add("VFBody",
        fontName="Helvetica", fontSize=10, leading=15,
        textColor=TEXT_SOFT, spaceAfter=6)
    add("VFBodySmall",
        fontName="Helvetica", fontSize=9, leading=13,
        textColor=MUTED, spaceAfter=4)
    add("VFBold",
        fontName="Helvetica-Bold", fontSize=10, leading=15,
        textColor=TEXT, spaceAfter=4)
    add("VFItalic",
        fontName="Helvetica-Oblique", fontSize=10, leading=15,
        textColor=TEXT_SOFT, spaceAfter=6)
    add("VFScoreBig",
        fontName="Helvetica-Bold", fontSize=48, leading=54,
        textColor=CORAL, spaceAfter=2)
    add("VFScoreLabelBig",
        fontName="Helvetica-Bold", fontSize=11, leading=14,
        textColor=CORAL_DARK, spaceAfter=8)
    add("VFRecommendation",
        fontName="Helvetica-Bold", fontSize=13, leading=17,
        textColor=SEAWEED, spaceAfter=6)
    add("VFVerdict",
        fontName="Helvetica-BoldOblique", fontSize=11, leading=16,
        textColor=TEXT, spaceAfter=10)
    add("VFLabel",
        fontName="Helvetica-Bold", fontSize=8, leading=11,
        textColor=MUTED_2, spaceAfter=1, spaceBefore=8)
    add("VFRankNum",
        fontName="Helvetica-Bold", fontSize=10, leading=13,
        textColor=MUTED_2)

    return s


def _divider(color=LINE, thickness=0.5):
    return HRFlowable(width="100%", thickness=thickness, color=color, spaceAfter=8, spaceBefore=4)


def _page_header(canvas, doc):
    """Draws a slim coral top bar + page number footer on every page."""
    w, h = letter
    canvas.saveState()
    # top bar
    canvas.setFillColor(CORAL)
    canvas.rect(0, h - 22, w, 22, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.drawString(0.7 * inch, h - 14, "VENTURA FLOW  ·  RESEARCH MEMO PACK")
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(w - 0.7 * inch, h - 14, doc.run_label)
    # footer
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 8)
    canvas.drawCentredString(w / 2, 0.45 * inch, f"Page {canvas.getPageNumber()}")
    canvas.restoreState()


def _score_pill_table(scores_dict: dict[str, float]) -> Table:
    """Renders a row of label/value cells styled as score pills."""
    headers = []
    values = []
    for label, val in scores_dict.items():
        headers.append(Paragraph(
            f'<font color="{MUTED.hexval()}" size="7"><b>{label.upper()}</b></font>',
            ParagraphStyle("ph", fontName="Helvetica-Bold", fontSize=7, textColor=MUTED)
        ))
        col = _score_color(val)
        values.append(Paragraph(
            f'<font color="{col.hexval()}" size="14"><b>{val:.0f}</b></font>',
            ParagraphStyle("pv", fontName="Helvetica-Bold", fontSize=14,
                           textColor=col, leading=18)
        ))

    n = len(scores_dict)
    col_w = (6.6 * inch) / n
    t = Table(
        [headers, values],
        colWidths=[col_w] * n,
        rowHeights=[14, 22],
    )
    t.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("LINEBELOW", (0, 0), (-1, 0), 0.3, LINE),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("ROUNDEDCORNERS", [6, 6, 6, 6]),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def _overview_table(rows: list[dict], styles) -> Table:
    """Summary table: rank, title, deep badge, composite, vc-fit, novelty, credibility."""
    header_style = ParagraphStyle(
        "OHdr", fontName="Helvetica-Bold", fontSize=8, textColor=MUTED_2
    )
    cell_style = ParagraphStyle(
        "OCell", fontName="Helvetica", fontSize=8, textColor=TEXT_SOFT, leading=11
    )
    bold_cell = ParagraphStyle(
        "OCellB", fontName="Helvetica-Bold", fontSize=8, textColor=TEXT, leading=11
    )

    col_widths = [0.35 * inch, 3.3 * inch, 0.55 * inch, 0.7 * inch,
                  0.55 * inch, 0.55 * inch, 0.6 * inch]

    data = [[
        Paragraph("#", header_style),
        Paragraph("Paper", header_style),
        Paragraph("Type", header_style),
        Paragraph("Composite", header_style),
        Paragraph("VC-fit", header_style),
        Paragraph("Novelty", header_style),
        Paragraph("Credibility", header_style),
    ]]

    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), PANEL),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, LINE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (3, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, CREAM]),
        ("LINEBELOW", (0, 1), (-1, -2), 0.3, LINE),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]

    for i, r in enumerate(rows, 1):
        is_deep = r.get("has_judge")
        title_text = _esc(r["title"] or r["paper_id"])
        if len(title_text) > 80:
            title_text = title_text[:77] + "…"

        composite = r["composite"]
        comp_color = _score_color(composite)

        type_label = "Deep ★" if is_deep else "Triage"
        type_color = SEAWEED if is_deep else MUTED

        data.append([
            Paragraph(str(i), ParagraphStyle("rn", fontName="Helvetica-Bold",
                                             fontSize=8, textColor=MUTED_2)),
            Paragraph(title_text, bold_cell if is_deep else cell_style),
            Paragraph(f'<font color="{type_color.hexval()}">{type_label}</font>',
                      ParagraphStyle("tp", fontName="Helvetica-Bold", fontSize=7,
                                     textColor=type_color, leading=11)),
            Paragraph(f'<font color="{comp_color.hexval()}"><b>{composite:.0f}</b></font>',
                      ParagraphStyle("sc", fontName="Helvetica-Bold", fontSize=9,
                                     textColor=comp_color, leading=13)),
            Paragraph(f"{r['vc_fit']:.0f}", cell_style),
            Paragraph(f"{r['novelty']:.0f}", cell_style),
            Paragraph(f"{r['credibility']:.0f}", cell_style),
        ])

        if is_deep and r.get("investability_score") is not None:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), ARTICHOKE_BG))

    t = Table(data, colWidths=col_widths)
    t.setStyle(TableStyle(style_cmds))
    return t


def _stat_box(label: str, value: str, color: colors.Color = CORAL) -> Table:
    t = Table([[
        Paragraph(f'<font size="22" color="{color.hexval()}"><b>{value}</b></font>',
                  ParagraphStyle("sv", fontName="Helvetica-Bold", fontSize=22,
                                 textColor=color, leading=26)),
        Paragraph(f'<font size="9" color="{MUTED.hexval()}">{label}</font>',
                  ParagraphStyle("sl", fontName="Helvetica", fontSize=9,
                                 textColor=MUTED, leading=13)),
    ]], colWidths=[0.8 * inch, 1.4 * inch])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def _stats_row(ingested: int, triaged: int, deep: int) -> Table:
    boxes = [
        _stat_box("papers ingested", str(ingested), CORAL),
        _stat_box("passed triage", str(triaged), SUN),
        _stat_box("deep analyzed", str(deep), SEAWEED),
    ]
    t = Table([boxes], colWidths=[2.3 * inch, 2.3 * inch, 2.3 * inch],
              hAlign="LEFT")
    t.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def export_run_pdf(run_id: str, artifacts_dir: Path, top_k: int = 10) -> bytes:
    scores = get_triage_scores(run_id)[:top_k]
    if not scores:
        raise ValueError(f"No triage scores for run {run_id}")

    run_meta = get_run(run_id) or {}
    ingested  = run_meta.get("papers_ingested", "—")
    triaged   = run_meta.get("papers_passed_triage", "—")
    deep      = run_meta.get("papers_deep_analyzed", "—")
    mode      = run_meta.get("mode", "—")
    started   = run_meta.get("started_at", "")
    finished  = run_meta.get("finished_at", "")

    def fmt_dt(iso):
        if not iso:
            return "—"
        try:
            d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            return d.strftime("%b %d %Y · %H:%M UTC")
        except Exception:
            return iso

    styles = _styles()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter,
        leftMargin=0.7 * inch, rightMargin=0.7 * inch,
        topMargin=0.9 * inch, bottomMargin=0.7 * inch,
    )
    doc.run_label = f"{run_id}  ·  {mode}"
    story = []

    # ── COVER / OVERVIEW PAGE ──────────────────────────────────────────────

    story.append(Spacer(1, 0.15 * inch))
    story.append(Paragraph("Research Memo Pack", styles["VFTitle"]))
    story.append(Paragraph(f"Run {run_id}  ·  {mode}  ·  started {fmt_dt(started)}", styles["VFSubtitle"]))
    if finished:
        story.append(Paragraph(f"Finished {fmt_dt(finished)}", styles["VFSubtitle"]))
    story.append(Spacer(1, 0.18 * inch))
    story.append(_divider(CORAL, 1.5))
    story.append(Spacer(1, 0.1 * inch))

    story.append(Paragraph("Pipeline Summary", styles["VFSection"]))
    story.append(_stats_row(ingested, triaged, deep))
    story.append(Spacer(1, 0.2 * inch))

    # Annotate each score with judge/deck availability
    overview_rows = []
    paper_data: list[tuple[Any, Any, Any, Any]] = []  # (score, paper, judge, deck)
    for s in scores:
        paper = get_paper(s.paper_id)
        paper_dir = artifacts_dir / s.paper_id.replace(":", "_")
        judge = None
        deck = None
        if paper_dir.exists():
            j_path = paper_dir / "judge_evaluation.json"
            d_path = paper_dir / "pitch_deck.json"
            if j_path.exists():
                try:
                    judge = json.loads(j_path.read_text())
                except Exception:
                    pass
            if d_path.exists():
                try:
                    deck = json.loads(d_path.read_text())
                except Exception:
                    pass
        paper_data.append((s, paper, judge, deck))
        overview_rows.append({
            "paper_id": s.paper_id,
            "title": paper.title if paper else s.paper_id,
            "has_judge": judge is not None,
            "composite": s.composite,
            "vc_fit": s.vc_fit,
            "novelty": s.novelty,
            "credibility": s.credibility,
            "investability_score": judge.get("investability_score") if judge else None,
        })

    story.append(Paragraph(f"Top {len(scores)} Papers — Overview", styles["VFSection"]))
    story.append(_overview_table(overview_rows, styles))

    deep_count = sum(1 for r in overview_rows if r["has_judge"])
    triage_count = len(overview_rows) - deep_count
    legend_parts = []
    if deep_count:
        legend_parts.append(f"<b>★ Deep</b> — {deep_count} paper(s) with full analyst memo")
    if triage_count:
        legend_parts.append(f"Triage — {triage_count} paper(s) scored at triage only")
    if legend_parts:
        story.append(Paragraph("  ·  ".join(legend_parts), styles["VFBodySmall"]))

    story.append(PageBreak())

    # ── PAPER PAGES ───────────────────────────────────────────────────────

    for rank, (s, paper, judge, deck) in enumerate(paper_data, 1):
        if not paper:
            continue

        is_deep = judge is not None
        story.append(Spacer(1, 0.05 * inch))

        # Rank + title
        story.append(Paragraph(
            f'<font color="{MUTED.hexval()}">#{rank}</font>  {_esc(paper.title)}',
            styles["VFPaperTitle"]
        ))

        # Authors + meta
        authors = ", ".join(a.name for a in paper.authors[:5])
        if len(paper.authors) > 5:
            authors += f" + {len(paper.authors) - 5} more"
        meta = f"{authors or 'Unknown authors'}  ·  {paper.year or '—'}  ·  {paper.venue or '—'}"
        if paper.citation_count:
            meta += f"  ·  {paper.citation_count} citations"
        story.append(Paragraph(_esc(meta), styles["VFMeta"]))
        story.append(_divider())

        if is_deep:
            # ── Deep-dive layout ─────────────────────────────────────────

            inv_score = judge.get("investability_score", "—")
            recommendation = judge.get("recommendation", "")
            verdict = judge.get("one_line_verdict") or judge.get("investability_rationale", "")

            # Large score + recommendation side-by-side
            inv_color = _score_color(float(inv_score)) if str(inv_score).isdigit() else CORAL
            score_para = Paragraph(
                f'<font color="{inv_color.hexval()}" size="44"><b>{inv_score}</b></font>'
                f'<font color="{MUTED.hexval()}" size="16"> /100</font>',
                ParagraphStyle("big", fontName="Helvetica-Bold", fontSize=44,
                               textColor=inv_color, leading=50)
            )
            label_para = Paragraph(
                '<font size="9">INVESTABILITY SCORE</font>',
                ParagraphStyle("lbl", fontName="Helvetica-Bold", fontSize=9,
                               textColor=MUTED_2, leading=12)
            )
            rec_para = Paragraph(
                f'<font color="{SEAWEED.hexval()}" size="13"><b>{_esc(recommendation)}</b></font>',
                styles["VFRecommendation"]
            )
            if verdict:
                verdict_para = Paragraph(f'"{_esc(verdict)}"', styles["VFVerdict"])
            else:
                verdict_para = Spacer(1, 0)

            score_block = Table(
                [[score_para, [rec_para, verdict_para]]],
                colWidths=[2.1 * inch, 4.5 * inch],
            )
            score_block.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (-1, -1), CORAL_BG),
                ("BOX", (0, 0), (-1, -1), 0.5, CORAL),
                ("LEFTPADDING", (0, 0), (-1, -1), 14),
                ("RIGHTPADDING", (0, 0), (-1, -1), 14),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]))
            story.append(score_block)
            story.append(Spacer(1, 10))

            # Triage scores row
            story.append(_score_pill_table({
                "Composite": s.composite,
                "VC-fit": s.vc_fit,
                "Novelty": s.novelty,
                "Credibility": s.credibility,
            }))
            story.append(Spacer(1, 8))

            # Triage rationale
            story.append(Paragraph("Triage Rationale", styles["VFLabel"]))
            story.append(Paragraph(f"<i>{_esc(s.rationale)}</i>", styles["VFItalic"]))

            # Memo sections from pitch_deck if available
            if deck:
                for field_key, field_label in [
                    ("memo_title", None),
                    ("tldr", "TL;DR"),
                    ("market_opportunity", "Market Opportunity"),
                    ("technical_edge", "Technical Edge"),
                    ("risks", "Key Risks"),
                    ("commercialization_path", "Commercialization Path"),
                    ("why_now", "Why Now"),
                ]:
                    val = deck.get(field_key)
                    if not val:
                        continue
                    if field_key == "memo_title":
                        story.append(Paragraph(_esc(val), styles["VFSection"]))
                    else:
                        story.append(Paragraph(field_label, styles["VFLabel"]))
                        if isinstance(val, list):
                            for item in val:
                                story.append(Paragraph(f"• {_esc(str(item))}", styles["VFBody"]))
                        else:
                            story.append(Paragraph(_esc(str(val)), styles["VFBody"]))

            # Judge sections
            for field_key, field_label in [
                ("strengths", "Strengths"),
                ("weaknesses", "Weaknesses"),
                ("key_questions", "Key Questions"),
            ]:
                val = judge.get(field_key)
                if not val:
                    continue
                story.append(Paragraph(field_label, styles["VFLabel"]))
                if isinstance(val, list):
                    for item in val:
                        story.append(Paragraph(f"• {_esc(str(item))}", styles["VFBody"]))
                else:
                    story.append(Paragraph(_esc(str(val)), styles["VFBody"]))

        else:
            # ── Triage-only layout ───────────────────────────────────────

            story.append(_score_pill_table({
                "Composite": s.composite,
                "VC-fit": s.vc_fit,
                "Novelty": s.novelty,
                "Credibility": s.credibility,
            }))
            story.append(Spacer(1, 8))
            story.append(Paragraph("Triage Rationale", styles["VFLabel"]))
            story.append(Paragraph(f"<i>{_esc(s.rationale)}</i>", styles["VFItalic"]))

        # Abstract (shared)
        abstract = (paper.abstract or "").strip()
        if abstract:
            story.append(Paragraph("Abstract", styles["VFLabel"]))
            truncated = abstract[:1800]
            if len(abstract) > 1800:
                truncated += "…"
            story.append(Paragraph(_esc(truncated), styles["VFBodySmall"]))

        story.append(PageBreak())

    doc.build(story, onFirstPage=_page_header, onLaterPages=_page_header)
    return buffer.getvalue()
