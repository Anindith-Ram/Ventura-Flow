"""Ollama-backed scoring tests — exercises real llama3.1:8b end-to-end.

These tests are marked `slow` because each paper takes ~2-4s to score.
Run with: pytest tests/test_scoring_ollama.py -v -m slow
"""
from __future__ import annotations

import os
import pytest

from tests.conftest import requires_ollama
from shared.models import Paper

pytestmark = pytest.mark.slow


@pytest.fixture(autouse=True)
def use_ollama_backend(monkeypatch):
    """Force Ollama backend for all tests in this module."""
    monkeypatch.setenv("SCORER_BACKEND", "ollama")
    monkeypatch.setenv("SCORER_MODEL", "llama3.1:8b")
    # Reload settings so the env change takes effect
    import importlib
    import shared.config
    importlib.reload(shared.config)
    from shared.config import settings
    monkeypatch.setattr(settings, "scorer_backend", "ollama")
    monkeypatch.setattr(settings, "scorer_model", "llama3.1:8b")


@requires_ollama
def test_alphafold_paper_scores_above_threshold(alphafold_paper):
    """AlphaFold — flagship ML breakthrough — must score ≥ 0.55."""
    from investor_signal_mcp.server import compute_investor_score
    score = compute_investor_score(alphafold_paper)
    assert score.scorer_used == "ollama", f"Expected ollama scorer, got: {score.scorer_used}"
    assert score.total_score >= 0.55, (
        f"AlphaFold scored {score.total_score:.3f} — expected ≥ 0.55.\n"
        f"Features: {score.features.model_dump()}\nCaveats: {score.caveats}"
    )
    assert score.total_score >= 0.45, "Must pass default threshold of 0.45"


@requires_ollama
def test_position_paper_scores_low(position_paper):
    """Vision/position paper with no implementation must score < 0.40."""
    from investor_signal_mcp.server import compute_investor_score
    score = compute_investor_score(position_paper)
    assert score.scorer_used == "ollama"
    assert score.total_score < 0.40, (
        f"Position paper scored {score.total_score:.3f} — expected < 0.40.\n"
        f"Features: {score.features.model_dump()}"
    )
    assert score.features.conceptual_penalty >= 0.4, (
        f"Expected high conceptual_penalty, got {score.features.conceptual_penalty:.3f}"
    )


@requires_ollama
def test_ranking_order_alphafold_beats_position_paper(alphafold_paper, position_paper):
    """AlphaFold must rank higher than a position paper."""
    from investor_signal_mcp.server import compute_investor_score
    af_score = compute_investor_score(alphafold_paper)
    pos_score = compute_investor_score(position_paper)
    assert af_score.total_score > pos_score.total_score, (
        f"AlphaFold ({af_score.total_score:.3f}) should beat position paper ({pos_score.total_score:.3f})"
    )


@requires_ollama
def test_calibration_ranking_order(alphafold_paper, crispr_paper, lidar_hardware_paper,
                                   workshop_paper, position_paper):
    """Ordinal ranking: AlphaFold/CRISPR/LiDAR >> workshop >> position paper."""
    from investor_signal_mcp.server import compute_investor_score
    scores = {
        "alphafold": compute_investor_score(alphafold_paper).total_score,
        "crispr": compute_investor_score(crispr_paper).total_score,
        "lidar": compute_investor_score(lidar_hardware_paper).total_score,
        "workshop": compute_investor_score(workshop_paper).total_score,
        "position": compute_investor_score(position_paper).total_score,
    }
    # All substantive papers must beat the position paper
    for name in ("alphafold", "crispr", "lidar"):
        assert scores[name] > scores["position"], (
            f"{name} ({scores[name]:.3f}) should score above position paper ({scores['position']:.3f})"
        )
    # All substantive papers must beat the workshop toy
    for name in ("alphafold", "crispr", "lidar"):
        assert scores[name] > scores["workshop"], (
            f"{name} ({scores[name]:.3f}) should score above workshop paper ({scores['workshop']:.3f})"
        )


@requires_ollama
def test_feature_scores_in_range(alphafold_paper):
    """Every feature score must be in [0.0, 1.0] and total in [0.0, 1.0]."""
    from investor_signal_mcp.server import compute_investor_score
    score = compute_investor_score(alphafold_paper)
    for field, value in score.features.model_dump().items():
        assert 0.0 <= value <= 1.0, f"Feature {field} = {value} out of range [0, 1]"
    assert 0.0 <= score.total_score <= 1.0
    assert 0.0 <= score.confidence <= 1.0


@requires_ollama
def test_score_distribution_on_real_papers(alphafold_s2_papers):
    """On a set of real AlphaFold papers: median ≥ 0.35, max ≥ 0.55, no NaN."""
    from investor_signal_mcp.server import compute_investor_score
    import math
    scores = [compute_investor_score(p).total_score for p in alphafold_s2_papers]
    assert len(scores) > 0, "No papers to score"
    assert all(not math.isnan(s) for s in scores), "NaN found in scores"
    assert all(0.0 <= s <= 1.0 for s in scores), "Score out of [0,1] range"
    sorted_scores = sorted(scores)
    n = len(sorted_scores)
    median = sorted_scores[n // 2]
    assert median >= 0.35, f"Median score {median:.3f} too low — expected ≥ 0.35"
    assert sorted_scores[-1] >= 0.55, f"Max score {sorted_scores[-1]:.3f} too low — expected ≥ 0.55"


def test_ollama_json_parse_resilience(monkeypatch, alphafold_paper):
    """_evaluate_with_ollama must handle messy LLM output gracefully."""
    messy_outputs = [
        # Prose before JSON
        'Here is my analysis:\n{"novelty":0.8,"investor_value":0.7,"buildability":0.6,"defensibility":0.5,"evidence_strength":0.9,"execution_risk":0.3,"conceptual_penalty":0.1,"top_signals":["a","b","c"],"caveats":["x","y","z"]}',
        # Thinking tags wrapping JSON
        '<think>Let me evaluate...</think>\n{"novelty":0.8,"investor_value":0.7,"buildability":0.6,"defensibility":0.5,"evidence_strength":0.9,"execution_risk":0.3,"conceptual_penalty":0.1,"top_signals":["a","b","c"],"caveats":["x","y","z"]}',
    ]
    from investor_signal_mcp.server import _extract_json_object
    for output in messy_outputs:
        parsed = _extract_json_object(output)
        assert parsed, f"Failed to parse: {output[:80]}"
        assert "novelty" in parsed
        assert 0.0 <= float(parsed["novelty"]) <= 1.0


@requires_ollama
def test_ollama_scorer_used_field(alphafold_paper):
    """scorer_used field must be 'ollama' when Ollama is running."""
    from investor_signal_mcp.server import compute_investor_score
    score = compute_investor_score(alphafold_paper)
    assert score.scorer_used == "ollama"
