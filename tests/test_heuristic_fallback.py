"""Heuristic fallback scorer tests — fast, no Ollama required.

These run with SCORER_BACKEND=heuristic and validate that the safety-net
scorer produces sensible results across paper types.

Run with: pytest tests/test_heuristic_fallback.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def use_heuristic_backend(monkeypatch):
    """Force heuristic backend for all tests in this module."""
    monkeypatch.setenv("SCORER_BACKEND", "heuristic")
    import importlib
    import shared.config
    importlib.reload(shared.config)
    from shared.config import settings
    monkeypatch.setattr(settings, "scorer_backend", "heuristic")


def test_alphafold_heuristic_beats_position_paper(alphafold_paper, position_paper):
    """Heuristic must rank AlphaFold above a position paper."""
    from investor_signal_mcp.server import compute_investor_score
    af = compute_investor_score(alphafold_paper)
    pos = compute_investor_score(position_paper)
    assert af.total_score > pos.total_score, (
        f"Heuristic: AlphaFold ({af.total_score:.3f}) should beat position paper ({pos.total_score:.3f})"
    )


def test_heuristic_scorer_used_field(alphafold_paper, monkeypatch):
    """scorer_used must be 'heuristic' when Ollama is off."""
    from investor_signal_mcp.server import compute_investor_score
    score = compute_investor_score(alphafold_paper)
    assert score.scorer_used == "heuristic", f"Expected 'heuristic', got '{score.scorer_used}'"


def test_conceptual_penalty_not_fired_by_framework(alphafold_paper):
    """'framework' in abstract must not trigger conceptual_penalty >= 0.4."""
    from shared.models import Paper
    from investor_signal_mcp.server import compute_investor_score

    paper_with_framework = Paper(
        paper_id="test-framework-word",
        title="A novel deep learning framework for protein structure prediction",
        abstract=(
            "We propose a new framework for protein structure prediction that outperforms "
            "state-of-the-art methods. Our implementation demonstrates results on CASP14 "
            "benchmarks with significant improvement. Code is available. The framework "
            "architecture uses attention mechanisms and novel training objectives."
        ),
        year=2022,
        citation_count=500,
        is_open_access=True,
        fields_of_study=["Machine Learning"],
        source="semantic_scholar",
    )
    score = compute_investor_score(paper_with_framework)
    assert score.features.conceptual_penalty < 0.4, (
        f"'framework' in abstract should not trigger conceptual_penalty "
        f"(got {score.features.conceptual_penalty:.3f})"
    )


def test_position_paper_has_high_conceptual_penalty(position_paper):
    """Position paper with many speculative phrases must have conceptual_penalty >= 0.4."""
    from investor_signal_mcp.server import compute_investor_score
    score = compute_investor_score(position_paper)
    assert score.features.conceptual_penalty >= 0.4, (
        f"Expected high conceptual_penalty for position paper, got {score.features.conceptual_penalty:.3f}"
    )


def test_ml_paper_buildability_non_zero(alphafold_paper):
    """ML papers with 'model', 'architecture', 'code' should score buildability > 0."""
    from investor_signal_mcp.server import compute_investor_score
    score = compute_investor_score(alphafold_paper)
    assert score.features.buildability > 0.0, (
        f"AlphaFold buildability should be > 0, got {score.features.buildability:.3f}"
    )


def test_citation_count_boosts_score():
    """Higher citation_count should produce a higher score (all else equal)."""
    from shared.models import Paper
    from investor_signal_mcp.server import compute_investor_score

    base_abstract = (
        "We propose a new approach for protein structure prediction. "
        "Our implementation outperforms baselines on CASP14 benchmarks. "
        "Model and code are available. Evaluation confirms results."
    )
    low_cites = Paper(
        paper_id="test-low-cites", title="Paper low citations",
        abstract=base_abstract, year=2022, citation_count=0,
        is_open_access=True, fields_of_study=[], source="semantic_scholar",
    )
    high_cites = Paper(
        paper_id="test-high-cites", title="Paper high citations",
        abstract=base_abstract, year=2022, citation_count=5000,
        is_open_access=True, fields_of_study=[], source="semantic_scholar",
    )
    low_score = compute_investor_score(low_cites).total_score
    high_score = compute_investor_score(high_cites).total_score
    assert high_score >= low_score, (
        f"High-citation paper ({high_score:.3f}) should score >= low-citation ({low_score:.3f})"
    )


def test_all_feature_scores_in_range_across_paper_types(
    alphafold_paper, position_paper, workshop_paper, lidar_hardware_paper, crispr_paper
):
    """All feature scores must be in [0.0, 1.0] for every paper type."""
    from investor_signal_mcp.server import compute_investor_score
    for paper in (alphafold_paper, position_paper, workshop_paper, lidar_hardware_paper, crispr_paper):
        score = compute_investor_score(paper)
        for field, value in score.features.model_dump().items():
            assert 0.0 <= value <= 1.0, (
                f"{paper.paper_id}: feature '{field}' = {value} out of [0, 1]"
            )


def test_term_ratio_boundary_cases():
    """_evaluate_with_fallback_heuristics handles edge cases without error."""
    from shared.models import Paper
    from investor_signal_mcp.server import compute_investor_score

    # Empty abstract
    empty_paper = Paper(
        paper_id="test-empty", title="A paper",
        abstract=None, year=2022, citation_count=0,
        fields_of_study=[], source="semantic_scholar",
    )
    score = compute_investor_score(empty_paper)
    assert 0.0 <= score.total_score <= 1.0

    # Title only with one strong signal
    title_only = Paper(
        paper_id="test-title-only",
        title="Novel breakthrough: state-of-the-art protein prediction via deep learning model",
        abstract=None, year=2023, citation_count=0,
        fields_of_study=[], source="semantic_scholar",
    )
    score2 = compute_investor_score(title_only)
    assert 0.0 <= score2.total_score <= 1.0
    # Should have some novelty signal from title
    assert score2.features.novelty > 0.0
