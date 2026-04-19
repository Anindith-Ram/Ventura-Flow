"""Autonomous mode — keep discovering papers until a stop condition triggers.

Stop conditions (first to hit wins):
  - time_limit_minutes elapsed
  - paper_cap papers ingested in total across rounds

Each round:
  1. Query Planner receives angles already covered → emits FRESH angles
  2. Orchestrator runs metadata → dedup → triage (not deep analysis — too slow)
  3. Top-K leaderboard updated with new triage scores

After the loop ends, deep analysis (bull/bear/judge) runs on the overall
top-K papers from the accumulated leaderboard.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from shared.db import get_papers_by_ids, save_run, save_triage_scores
from shared.models import RunConfig, RunSummary, TriageScore, VCProfile

from orchestration.dedup import dedupe_papers
from orchestration.deep_ingest import ingest_full_text
from orchestration.diversity import select_top
from orchestration.events import make_event
from orchestration.pipeline import PipelineRunner, _paper_to_agent_dict  # noqa: F401

from agents.query_planner import plan_queries
from agents.triage_agent import triage_paper

logger = logging.getLogger(__name__)


async def run_autonomous(
    runner: PipelineRunner,
    profile: VCProfile,
    config: RunConfig,
) -> RunSummary:
    run_id = datetime.utcnow().strftime("auto_%Y%m%d_%H%M%S")
    started = datetime.utcnow()
    deadline = started + timedelta(minutes=config.autonomous_time_limit_minutes)

    from shared.config import settings
    artifacts_dir = settings.runs_dir / run_id
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    await runner._emit(
        run_id, "run",
        f"Autonomous mode — stop after {config.autonomous_time_limit_minutes} min "
        f"or {config.autonomous_paper_cap} papers",
        "stage_start", mode="autonomous",
    )

    covered_angles: list[str] = []
    all_papers: dict[str, object] = {}  # paper_id -> Paper
    all_scores: dict[str, TriageScore] = {}  # paper_id -> best score seen

    round_no = 0
    while True:
        round_no += 1
        remaining_time = (deadline - datetime.utcnow()).total_seconds()
        if remaining_time <= 0:
            await runner._emit(run_id, "auto", f"Time limit reached after round {round_no - 1}", "stage_end")
            break
        if len(all_papers) >= config.autonomous_paper_cap:
            await runner._emit(
                run_id, "auto",
                f"Paper cap ({config.autonomous_paper_cap}) reached after round {round_no - 1}",
                "stage_end",
            )
            break

        await runner._emit(
            run_id, "auto",
            f"── Round {round_no} ── (time left: {int(remaining_time/60)}m, papers: {len(all_papers)})",
        )

        # Planner with exclude list
        queries = await asyncio.to_thread(
            plan_queries, profile, config.max_queries, covered_angles
        )
        for q in queries:
            if q["angle"] not in covered_angles:
                covered_angles.append(q["angle"])

        # Ingest
        round_papers = []
        for q in queries:
            if datetime.utcnow() >= deadline:
                break
            try:
                batch = await asyncio.to_thread(
                    runner.openalex.search, q["query"], config.papers_per_query,
                    profile.year_from, profile.year_to,
                )
                round_papers.extend(batch)
                await runner._emit(
                    run_id, "auto", f"[R{round_no}/{q['angle']}] {len(batch)} papers",
                )
            except Exception as exc:
                await runner._emit(run_id, "auto", f"[R{round_no}] query failed: {exc}", "warn")

        # Filter to new (not already seen) + with abstract
        fresh = [p for p in round_papers if p.abstract and p.paper_id not in all_papers]
        if not fresh:
            await runner._emit(run_id, "auto", f"Round {round_no}: no new papers", "warn")
            continue

        # Enrich, dedup, triage
        try:
            await asyncio.to_thread(runner.openalex.enrich_authors, fresh)
        except Exception:
            pass
        fresh.sort(key=lambda p: p.citation_count, reverse=True)
        fresh = await asyncio.to_thread(dedupe_papers, fresh)

        from shared.db import upsert_papers
        upsert_papers(fresh)

        for p in fresh:
            all_papers[p.paper_id] = p

        round_scores = []
        for p in fresh:
            if datetime.utcnow() >= deadline:
                break
            s = await asyncio.to_thread(triage_paper, p, profile)
            round_scores.append(s)
            all_scores[p.paper_id] = s
            await runner._emit(
                run_id, "auto",
                f"[R{round_no}] {p.title[:60]} → {s.composite:.1f}",
                data={
                    "paper_id": p.paper_id, "title": p.title,
                    "composite": s.composite, "vc_fit": s.vc_fit,
                    "novelty": s.novelty, "credibility": s.credibility,
                    "rationale": s.rationale,
                },
            )

        save_triage_scores(run_id, round_scores)

        # Emit leaderboard snapshot
        top = sorted(all_scores.values(), key=lambda s: s.composite, reverse=True)[:10]
        await runner._emit(
            run_id, "auto",
            f"Leaderboard after round {round_no}: top score {top[0].composite:.1f}" if top else "empty",
            data={"leaderboard": [s.model_dump() for s in top]},
        )

    # ── Deep analysis on overall top-K ───────────────────────────────────────
    ranked = list(all_scores.values())
    passed = select_top(ranked, total_universe=len(ranked), enforce_diversity=True)
    deep_k = min(config.bull_bear_for_top_k, len(passed))
    await runner._emit(
        run_id, "auto",
        f"Running deep analysis on final top-{deep_k} of {len(passed)} gated papers",
        "stage_start",
    )

    top_papers = get_papers_by_ids([s.paper_id for s in passed[:deep_k]])
    top_by_id = {p.paper_id: p for p in top_papers}
    top_ordered = [top_by_id[s.paper_id] for s in passed[:deep_k] if s.paper_id in top_by_id]

    for p in top_ordered:
        await asyncio.to_thread(ingest_full_text, p)

    results = []
    for i, paper in enumerate(top_ordered, 1):
        paper_dir = artifacts_dir / paper.paper_id.replace(":", "_")
        paper_dir.mkdir(exist_ok=True)
        await runner._emit(run_id, "analysis", f"[{i}/{len(top_ordered)}] {paper.title[:70]}")
        try:
            r = await runner._run_bull_bear_judge(run_id, paper, paper_dir)
            results.append({"paper_id": paper.paper_id, **r})
        except Exception as exc:
            logger.exception("Analysis failed")
            await runner._emit(run_id, "analysis", f"Failed {paper.paper_id}: {exc}", "error")

    summary = RunSummary(
        run_id=run_id,
        started_at=started,
        finished_at=datetime.utcnow(),
        mode="autonomous",
        queries_planned=len(covered_angles),
        papers_ingested=len(all_papers),
        papers_passed_triage=len(passed),
        papers_deep_analyzed=len(results),
        top_paper_ids=[s.paper_id for s in passed],
        artifacts_dir=str(artifacts_dir),
    )
    import json as _json
    save_run(summary, _json.dumps(profile.model_dump(mode="json"), default=str))
    await runner._emit(
        run_id, "run",
        f"Autonomous run complete — {len(results)} memos, {len(all_papers)} papers scanned, "
        f"{round_no} rounds",
        "success",
    )
    return summary
