"""Unified 7-stage pipeline orchestrator.

Stages:
  1. Query Planner   — VC profile -> tailored search queries
  2. Metadata Ingest — OpenAlex search + author enrichment
  3. Dedup           — cosine similarity on abstracts
  4. Triage          — per-paper VC-fit / novelty / credibility + rationale
  5. Gate            — percentile top-K with diversity across subfields
  6. Deep Ingest     — PDF download + full-text extraction
  7. Bull/Bear/Judge — per-paper investment memo

Every stage emits events via the EventBus so terminal and GUI see the same
stream in real time.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

from shared.config import settings
from shared.db import (
    get_papers_by_ids,
    init_db,
    save_run,
    save_triage_scores,
    upsert_papers,
)
from shared.models import (
    Paper,
    PipelineEvent,
    RunConfig,
    RunSummary,
    VCProfile,
)

from orchestration.dedup import dedupe_papers
from orchestration.deep_ingest import ingest_full_text
from orchestration.digest import post_digest
from orchestration.diversity import select_top
from orchestration.events import EventBus, get_bus, make_event

from agents.query_planner import plan_queries
from agents.triage_agent import triage_paper
from agents import bull_researcher, bear_researcher, bull_analyst, bear_analyst, judge_agent

from papers_mcp.openalex import OpenAlexClient

logger = logging.getLogger(__name__)


# ── Runner ───────────────────────────────────────────────────────────────────

class PipelineRunner:
    def __init__(self, bus: EventBus | None = None) -> None:
        self.bus = bus or get_bus()
        self.openalex = OpenAlexClient()
        init_db()

    async def _emit(self, run_id: str, stage: str, message: str, level: str = "info", **data) -> None:
        await self.bus.emit(make_event(run_id, stage, message, level, **data))

    # ── Single-round run ─────────────────────────────────────────────────────
    async def run_once(
        self,
        profile: VCProfile,
        config: RunConfig,
        run_id: str | None = None,
        exclude_angles: list[str] | None = None,
    ) -> RunSummary:
        run_id = run_id or datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        started = datetime.utcnow()
        artifacts_dir = settings.runs_dir / run_id
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        await self._emit(run_id, "run", f"Starting run {run_id} (mode={config.mode})", "stage_start",
                         mode=config.mode, artifacts_dir=str(artifacts_dir))

        # ── 1. Plan queries ─────────────────────────────────────────────────
        await self._emit(run_id, "plan", "Query Planner reasoning about VC thesis...", "stage_start")
        queries = await asyncio.to_thread(
            plan_queries, profile, config.max_queries, exclude_angles or []
        )
        (artifacts_dir / "queries.json").write_text(json.dumps(queries, indent=2))
        await self._emit(
            run_id, "plan", f"Planned {len(queries)} queries",
            "stage_end", queries=queries, artifact="queries.json",
        )

        # ── 2. Metadata ingest ──────────────────────────────────────────────
        await self._emit(run_id, "ingest", "Searching OpenAlex...", "stage_start")
        all_papers: list[Paper] = []
        for q in queries:
            try:
                batch = await asyncio.to_thread(
                    self.openalex.search, q["query"], config.papers_per_query,
                    profile.year_from, profile.year_to,
                )
                all_papers.extend(batch)
                await self._emit(
                    run_id, "ingest", f"[{q['angle']}] '{q['query']}' → {len(batch)} papers",
                    data={"angle": q["angle"], "query": q["query"], "count": len(batch)},
                )
            except Exception as exc:
                await self._emit(run_id, "ingest", f"Query failed: {exc}", "warn")

        # Dedupe by paper_id first (same paper from multiple queries).
        seen_ids: set[str] = set()
        deduped: list[Paper] = []
        for p in all_papers:
            if p.paper_id not in seen_ids:
                seen_ids.add(p.paper_id)
                deduped.append(p)
        await self._emit(run_id, "ingest", f"Fetched {len(deduped)} unique papers")

        # Author enrichment
        try:
            await asyncio.to_thread(self.openalex.enrich_authors, deduped)
            await self._emit(run_id, "ingest", "Author metrics enriched (h-index, works count)")
        except Exception as exc:
            await self._emit(run_id, "ingest", f"Author enrichment skipped: {exc}", "warn")

        # Filter papers without abstracts (triage needs them)
        with_abstract = [p for p in deduped if p.abstract]
        if len(with_abstract) < len(deduped):
            await self._emit(
                run_id, "ingest",
                f"Dropped {len(deduped) - len(with_abstract)} papers without abstracts"
            )

        # Filter to open-access papers only (pdf_url present) so deep analysis
        # always has full text. Papers without a PDF are dropped here.
        with_pdf = [p for p in with_abstract if p.pdf_url]
        no_pdf_count = len(with_abstract) - len(with_pdf)
        if no_pdf_count:
            await self._emit(
                run_id, "ingest",
                f"Dropped {no_pdf_count} papers with no open-access PDF "
                f"({len(with_pdf)} remain for triage)",
                level="warn",
            )
        else:
            await self._emit(run_id, "ingest", f"All {len(with_pdf)} papers have open-access PDFs")

        upsert_papers(with_pdf)
        await self._emit(
            run_id, "ingest", f"Stored {len(with_pdf)} papers in DB",
            "stage_end", papers_ingested=len(with_pdf),
        )

        if not with_pdf:
            summary = RunSummary(
                run_id=run_id, started_at=started, finished_at=datetime.utcnow(),
                mode=config.mode, queries_planned=len(queries),
                papers_ingested=0, artifacts_dir=str(artifacts_dir),
            )
            save_run(summary, json.dumps(profile.model_dump(mode="json"), default=str))
            await self._emit(run_id, "run", "No open-access papers found — run complete", "warn")
            return summary

        # ── 3. Dedup (semantic) ─────────────────────────────────────────────
        await self._emit(run_id, "dedup", "Removing near-duplicates...", "stage_start")
        with_pdf.sort(key=lambda p: p.citation_count, reverse=True)
        unique = await asyncio.to_thread(dedupe_papers, with_pdf)
        await self._emit(
            run_id, "dedup", f"{len(unique)} unique papers (dropped {len(with_pdf)-len(unique)})",
            "stage_end",
        )

        # ── 4. Triage ───────────────────────────────────────────────────────
        await self._emit(run_id, "triage", f"Triaging {len(unique)} papers...", "stage_start")
        scores = []
        for i, p in enumerate(unique, 1):
            s = await asyncio.to_thread(triage_paper, p, profile)
            scores.append(s)
            await self._emit(
                run_id, "triage",
                f"[{i}/{len(unique)}] {p.title[:70]} → {s.composite:.1f}",
                data={
                    "paper_id": p.paper_id, "title": p.title,
                    "composite": s.composite, "vc_fit": s.vc_fit,
                    "novelty": s.novelty, "credibility": s.credibility,
                    "rationale": s.rationale, "subfield": s.subfield,
                },
            )
        save_triage_scores(run_id, scores)
        (artifacts_dir / "triage_scores.json").write_text(
            json.dumps([s.model_dump() for s in scores], indent=2)
        )
        await self._emit(run_id, "triage", "Triage complete", "stage_end")

        # ── 5. Gate (percentile + diversity) ────────────────────────────────
        await self._emit(run_id, "gate", "Selecting top papers with diversity...", "stage_start")
        passed = select_top(scores, total_universe=len(unique), enforce_diversity=True)
        await self._emit(
            run_id, "gate",
            f"{len(passed)} passed (of {len(unique)}); top score {passed[0].composite:.1f}" if passed
            else "0 papers passed the gate",
            "stage_end", passed_ids=[s.paper_id for s in passed],
        )

        # Only run deep analysis on top-K (user-configurable, default 5)
        deep_k = min(config.bull_bear_for_top_k, len(passed))
        deep_candidates = passed[:deep_k]

        # ── 6. Deep ingest (full text) ──────────────────────────────────────
        top_papers = get_papers_by_ids([s.paper_id for s in deep_candidates])
        top_papers_by_id = {p.paper_id: p for p in top_papers}
        top_ordered = [top_papers_by_id[s.paper_id] for s in deep_candidates if s.paper_id in top_papers_by_id]

        await self._emit(run_id, "deep_ingest", f"Downloading full text for top {len(top_ordered)}...", "stage_start")
        for p in top_ordered:
            text = await asyncio.to_thread(ingest_full_text, p)
            if text:
                await self._emit(
                    run_id, "deep_ingest",
                    f"✓ {p.title[:60]} ({len(text)} chars extracted)",
                    data={"paper_id": p.paper_id, "chars": len(text)},
                )
            else:
                reason = "no open-access PDF in OpenAlex" if not p.pdf_url else "PDF download/parse failed"
                await self._emit(
                    run_id, "deep_ingest",
                    f"– {p.title[:60]} ({reason} — analysis will use abstract only)",
                    "warn", data={"paper_id": p.paper_id},
                )
        await self._emit(run_id, "deep_ingest", "Deep ingest complete", "stage_end")

        # ── 7. Bull / Bear / Judge per paper ────────────────────────────────
        await self._emit(run_id, "analysis", f"Running bull/bear/judge on {len(top_ordered)} papers...", "stage_start")
        top_paper_results = []
        for i, paper in enumerate(top_ordered, 1):
            paper_dir = artifacts_dir / paper.paper_id.replace(":", "_")
            paper_dir.mkdir(exist_ok=True)
            await self._emit(
                run_id, "analysis",
                f"[{i}/{len(top_ordered)}] {paper.title[:70]}",
                data={"paper_id": paper.paper_id},
            )
            try:
                result = await self._run_bull_bear_judge(run_id, paper, paper_dir)
                top_paper_results.append({"paper_id": paper.paper_id, **result})
            except Exception as exc:
                logger.exception("Analysis failed for %s", paper.paper_id)
                await self._emit(
                    run_id, "analysis", f"Analysis failed for {paper.paper_id}: {exc}", "error"
                )

        (artifacts_dir / "analysis_results.json").write_text(
            json.dumps(top_paper_results, indent=2, default=str)
        )
        await self._emit(run_id, "analysis", "All analyses complete", "stage_end")

        # ── Summary ─────────────────────────────────────────────────────────
        summary = RunSummary(
            run_id=run_id,
            started_at=started,
            finished_at=datetime.utcnow(),
            mode=config.mode,
            queries_planned=len(queries),
            papers_ingested=len(with_pdf),
            papers_passed_triage=len(passed),
            papers_deep_analyzed=len(top_paper_results),
            top_paper_ids=[s.paper_id for s in passed],
            artifacts_dir=str(artifacts_dir),
        )
        save_run(summary, json.dumps(profile.model_dump(mode="json"), default=str))
        await self._emit(
            run_id, "run",
            f"Run complete — {len(top_paper_results)} memos in {artifacts_dir}",
            "success", artifacts_dir=str(artifacts_dir),
        )

        if profile.digest_webhook_url:
            sent = await asyncio.to_thread(post_digest, profile, summary)
            if sent:
                await self._emit(run_id, "run", "Digest posted to webhook", "success")
            else:
                await self._emit(run_id, "run", "Digest webhook failed", "warn")

        return summary

    # ── Bull / Bear / Judge ──────────────────────────────────────────────────
    async def _run_bull_bear_judge(self, run_id: str, paper: Paper, out_dir: Path) -> dict:
        paper_dict = _paper_to_agent_dict(paper)

        def _log(stage: str):
            def inner(msg: str) -> None:
                # Agents use a single-arg logger; surface as events synchronously.
                try:
                    self.bus.emit_sync(make_event(run_id, stage, msg))
                except Exception:
                    pass
            return inner

        # Researchers — skip web search (kept minimal / cost-conscious).
        bull_queries = await asyncio.to_thread(bull_researcher.generate_queries, paper_dict, _log("bull_research"))
        bear_queries = await asyncio.to_thread(bear_researcher.generate_queries, paper_dict, _log("bear_research"))

        # Empty search results (agentic mode; DDG disabled). Researchers still produce briefs.
        bull_results = {q: [] for q in bull_queries}
        bear_results = {q: [] for q in bear_queries}

        bull_brief = await asyncio.to_thread(bull_researcher.synthesize_brief, paper_dict, bull_results, _log("bull_research"))
        bear_brief = await asyncio.to_thread(bear_researcher.synthesize_brief, paper_dict, bear_results, _log("bear_research"))
        (out_dir / "bull_brief.md").write_text(bull_brief)
        (out_dir / "bear_brief.md").write_text(bear_brief)

        bull_thesis = await asyncio.to_thread(bull_analyst.run, paper_dict, bull_brief, _log("bull_analyst"))
        bear_critique = await asyncio.to_thread(bear_analyst.run, paper_dict, bear_brief, _log("bear_analyst"))
        (out_dir / "bull_thesis.md").write_text(bull_thesis)
        (out_dir / "bear_critique.md").write_text(bear_critique)

        # Judge — expects a state dict
        judge_state = {
            "title": paper.title,
            "source_type": paper.source,
            "abstract": paper.abstract or "",
            "authors": [a.name for a in paper.authors],
            "institution": paper.authors[0].affiliations[0] if paper.authors and paper.authors[0].affiliations else "",
            "bull_thesis": {"thesis_markdown": bull_thesis},
            "bear_thesis": {"critique_markdown": bear_critique},
            "evidence": [],
            "correction_guidance": "",
            "graph_context": "",
        }
        result = await asyncio.to_thread(judge_agent.judge_agent, judge_state)
        (out_dir / "judge_evaluation.json").write_text(
            json.dumps(result.get("judge_evaluation", {}), indent=2)
        )
        (out_dir / "pitch_deck.json").write_text(
            json.dumps(result.get("pitch_deck", {}), indent=2)
        )

        scout = result.get("scout_report", {})
        await self._emit(
            run_id, "analysis",
            f"Score {scout.get('score', '?')}/100 — {scout.get('recommendation', '?')}: {scout.get('summary', '')[:80]}",
            "success",
            data={
                "paper_id": paper.paper_id,
                "score": scout.get("score"),
                "recommendation": scout.get("recommendation"),
                "summary": scout.get("summary"),
            },
        )
        return {
            "score": scout.get("score"),
            "recommendation": scout.get("recommendation"),
            "summary": scout.get("summary"),
            "artifacts_dir": str(out_dir),
        }


def _paper_to_agent_dict(p: Paper) -> dict:
    """Adapt Paper → the dict shape the legacy bull/bear agents expect."""
    return {
        "paper_id": p.paper_id,
        "title": p.title,
        "abstract": p.abstract or "",
        "full_text": p.full_text[:20000] if p.full_text else "",
        "authors": [a.name for a in p.authors],
        "year": p.year,
        "venue": p.venue,
        "url": p.url,
        "doi": p.doi,
        "source": p.source,
        "citation_count": p.citation_count,
        "fields_of_study": p.fields_of_study,
    }
