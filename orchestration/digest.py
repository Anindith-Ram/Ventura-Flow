"""POST a post-run digest to a webhook (Slack or generic)."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from shared.db import get_papers_by_ids, get_triage_scores
from shared.models import RunSummary, VCProfile

logger = logging.getLogger(__name__)


def _slack_payload(summary: RunSummary, top: list[dict]) -> dict[str, Any]:
    header = f":sparkles: *Ventura Flow* — run `{summary.run_id}` complete"
    stats = (
        f"{summary.papers_ingested} ingested · "
        f"{summary.papers_passed_triage} triaged · "
        f"{summary.papers_deep_analyzed} deep"
    )
    lines = [f"*Top {len(top)} papers*"]
    for i, t in enumerate(top, 1):
        lines.append(f"{i}. *{t['composite']:.0f}* — {t['title'][:100]}")
        if t.get("rationale"):
            lines.append(f"   _{t['rationale'][:160]}_")
    return {
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": header}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": stats}]},
            {"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}},
        ]
    }


def _generic_payload(summary: RunSummary, top: list[dict]) -> dict[str, Any]:
    return {
        "run_id": summary.run_id,
        "mode": summary.mode,
        "started_at": summary.started_at.isoformat(),
        "finished_at": summary.finished_at.isoformat() if summary.finished_at else None,
        "papers_ingested": summary.papers_ingested,
        "papers_passed_triage": summary.papers_passed_triage,
        "papers_deep_analyzed": summary.papers_deep_analyzed,
        "top_papers": top,
    }


def build_digest(summary: RunSummary, top_k: int = 5) -> tuple[list[dict], list[str]]:
    scores = get_triage_scores(summary.run_id)[:top_k]
    papers = {p.paper_id: p for p in get_papers_by_ids([s.paper_id for s in scores])}
    top = [
        {
            "paper_id": s.paper_id,
            "title": papers[s.paper_id].title if s.paper_id in papers else s.paper_id,
            "composite": s.composite,
            "rationale": s.rationale,
            "subfield": s.subfield,
        }
        for s in scores
    ]
    return top, [s.paper_id for s in scores]


def post_digest(profile: VCProfile, summary: RunSummary) -> bool:
    url = (profile.digest_webhook_url or "").strip()
    if not url:
        return False
    top, _ = build_digest(summary)
    payload = _slack_payload(summary, top) if "slack.com" in url else _generic_payload(summary, top)
    try:
        r = httpx.post(url, json=payload, timeout=10)
        r.raise_for_status()
        logger.info("Digest POSTed to %s (%d)", url, r.status_code)
        return True
    except Exception as exc:
        logger.warning("Digest POST failed: %s", exc)
        return False
