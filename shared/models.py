"""Pydantic data models shared across all MCP servers."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class Author(BaseModel):
    name: str
    author_id: Optional[str] = None
    affiliations: list[str] = Field(default_factory=list)


class Paper(BaseModel):
    """Normalised paper record stored in SQLite + Qdrant."""

    paper_id: str                                   # Semantic Scholar / internal ID
    doi: Optional[str] = None
    title: str
    abstract: Optional[str] = None
    authors: list[Author] = Field(default_factory=list)
    year: Optional[int] = None
    venue: Optional[str] = None
    url: Optional[str] = None
    pdf_url: Optional[str] = None
    source: str = "unknown"                         # "semantic_scholar" | "openalex"
    citation_count: int = 0
    is_open_access: bool = False
    fields_of_study: list[str] = Field(default_factory=list)
    fetched_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def text_for_embedding(self) -> str:
        """Concatenated text used for generating embeddings."""
        parts = [self.title]
        if self.abstract:
            parts.append(self.abstract)
        if self.venue:
            parts.append(self.venue)
        if self.fields_of_study:
            parts.append(" ".join(self.fields_of_study))
        return " ".join(parts)

    def to_db_row(self) -> dict[str, Any]:
        return {
            "paper_id": self.paper_id,
            "doi": self.doi,
            "title": self.title,
            "abstract": self.abstract,
            "authors": "|".join(a.name for a in self.authors),
            "year": self.year,
            "venue": self.venue,
            "url": self.url,
            "pdf_url": self.pdf_url,
            "source": self.source,
            "citation_count": self.citation_count,
            "is_open_access": int(self.is_open_access),
            "fields_of_study": "|".join(self.fields_of_study),
            "fetched_at": self.fetched_at.isoformat(),
        }


class IngestResult(BaseModel):
    total_fetched: int
    total_upserted: int
    skipped_no_abstract: int
    errors: list[str] = Field(default_factory=list)


class SearchResult(BaseModel):
    paper: Paper
    score: float


class FeatureScores(BaseModel):
    recency: float = 0.0
    citation_velocity: float = 0.0
    domain_momentum: float = 0.0
    translational_potential: float = 0.0
    commercialization_hints: float = 0.0
    open_access_bonus: float = 0.0
    venue_prestige: float = 0.0


class InvestorScore(BaseModel):
    paper_id: str
    title: str
    total_score: float                              # 0.0 – 1.0
    confidence: float                               # 0.0 – 1.0
    features: FeatureScores
    top_signals: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    disclaimer: str = (
        "⚠️  NOT INVESTMENT ADVICE. Scores reflect research signal patterns only."
    )


class ClusterResult(BaseModel):
    cluster_id: int
    size: int
    representative_paper_ids: list[str]
    top_terms: list[str] = Field(default_factory=list)


class PipelineRun(BaseModel):
    run_id: str
    query: str
    total_papers_ingested: int
    total_embedded: int
    top_investor_papers: list[InvestorScore]
    ocr_triggered_for: list[str]           # paper IDs that went through OCR
    artifacts_dir: str
    started_at: datetime
    finished_at: Optional[datetime] = None
