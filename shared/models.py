"""Pydantic data models shared across the pipeline."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ── Authors ─────────────────────────────────────────────────────────────────

class Author(BaseModel):
    name: str
    author_id: Optional[str] = None
    affiliations: list[str] = Field(default_factory=list)
    h_index: Optional[int] = None
    works_count: Optional[int] = None
    cited_by_count: Optional[int] = None


# ── Papers ──────────────────────────────────────────────────────────────────

class Paper(BaseModel):
    """Normalised paper record stored in SQLite."""

    paper_id: str
    doi: Optional[str] = None
    title: str
    abstract: Optional[str] = None
    authors: list[Author] = Field(default_factory=list)
    year: Optional[int] = None
    venue: Optional[str] = None
    url: Optional[str] = None
    pdf_url: Optional[str] = None
    source: str = "openalex"
    citation_count: int = 0
    is_open_access: bool = False
    fields_of_study: list[str] = Field(default_factory=list)
    full_text: Optional[str] = None
    fetched_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def text_for_embedding(self) -> str:
        parts = [self.title]
        if self.abstract:
            parts.append(self.abstract)
        if self.fields_of_study:
            parts.append(" ".join(self.fields_of_study))
        return " ".join(parts)

    @property
    def max_author_h_index(self) -> int:
        return max((a.h_index or 0) for a in self.authors) if self.authors else 0

    def to_db_row(self) -> dict[str, Any]:
        import json as _json
        return {
            "paper_id": self.paper_id,
            "doi": self.doi,
            "title": self.title,
            "abstract": self.abstract,
            "authors_json": _json.dumps([a.model_dump() for a in self.authors]),
            "year": self.year,
            "venue": self.venue,
            "url": self.url,
            "pdf_url": self.pdf_url,
            "source": self.source,
            "citation_count": self.citation_count,
            "is_open_access": int(self.is_open_access),
            "fields_of_study": "|".join(self.fields_of_study),
            "full_text": self.full_text,
            "fetched_at": self.fetched_at.isoformat(),
        }


# ── VC profile ──────────────────────────────────────────────────────────────

class VCProfile(BaseModel):
    """Global VC preference profile — drives query planning and triage."""

    # Identity (shown on the welcome page)
    user_name: str = ""
    firm_name: str = ""

    # Thesis (freetext — Query Planner reasons about this)
    thesis: str = ""
    sectors: list[str] = Field(default_factory=list)
    stage: Literal["pre-seed", "seed", "series-a", "series-b", "growth", "any"] = "any"
    geography: list[str] = Field(default_factory=list)
    deal_breakers: list[str] = Field(default_factory=list)

    # Author weighting (0.0 = ignored, 1.0 = primary signal)
    weight_vc_fit: float = 0.5
    weight_novelty: float = 0.3
    weight_author_credibility: float = 0.2
    min_h_index: int = 0  # soft floor — not a hard filter

    # Ingestion window
    year_from: int = 2022
    year_to: Optional[int] = None

    # Post-run digest: if set, POSTs a summary JSON to this URL when an
    # autonomous/single run finishes. Compatible with Slack incoming webhooks
    # (if the URL contains 'slack.com', payload shape is a Slack message).
    digest_webhook_url: Optional[str] = None

    # Template name (for the GUI preset dropdown)
    template: Optional[str] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ── Run config ──────────────────────────────────────────────────────────────

class RunConfig(BaseModel):
    """Per-run parameters (chosen in the GUI before Start)."""

    mode: Literal["single", "autonomous"] = "single"
    max_queries: int = 6
    papers_per_query: int = 20
    autonomous_time_limit_minutes: int = 60
    autonomous_paper_cap: int = 200
    bull_bear_for_top_k: int = 5  # only run deep analysis on top-K after triage


# ── Triage ──────────────────────────────────────────────────────────────────

class TriageScore(BaseModel):
    paper_id: str
    vc_fit: float        # 0-100
    novelty: float       # 0-100
    credibility: float   # 0-100
    composite: float     # weighted sum, 0-100
    rationale: str       # one-sentence "why"
    subfield: str = ""   # for diversity


# ── Events (for WebSocket streaming) ────────────────────────────────────────

class PipelineEvent(BaseModel):
    run_id: str
    stage: str
    level: Literal["info", "warn", "error", "success", "stage_start", "stage_end"] = "info"
    message: str
    data: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ── Run artefacts ───────────────────────────────────────────────────────────

class IngestResult(BaseModel):
    total_fetched: int
    total_upserted: int
    skipped_no_abstract: int
    errors: list[str] = Field(default_factory=list)


class RunSummary(BaseModel):
    run_id: str
    started_at: datetime
    finished_at: Optional[datetime] = None
    mode: Literal["single", "autonomous"]
    queries_planned: int = 0
    papers_ingested: int = 0
    papers_passed_triage: int = 0
    papers_deep_analyzed: int = 0
    top_paper_ids: list[str] = Field(default_factory=list)
    artifacts_dir: str = ""
