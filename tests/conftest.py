"""Shared fixtures for the Ventura-Flow test suite.

Requires:
    - Ollama running at http://localhost:11434
    - llama3.1:8b pulled (ollama pull llama3.1:8b)

Run with:
    pytest tests/ -v -m slow      # includes Ollama-backed tests
    pytest tests/ -v -m "not slow" # heuristic-only (fast)
"""
from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

# Ensure project root is on path for imports
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Ollama availability check
# ---------------------------------------------------------------------------

def _ollama_reachable() -> bool:
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5) as r:
            import json
            data = json.loads(r.read())
            models = [m.get("name", "") for m in data.get("models", [])]
            return any("llama3.1" in m for m in models)
    except Exception:
        return False


OLLAMA_AVAILABLE = _ollama_reachable()

requires_ollama = pytest.mark.skipif(
    not OLLAMA_AVAILABLE,
    reason="Ollama not running or llama3.1:8b not pulled. Run: ollama pull llama3.1:8b",
)


# ---------------------------------------------------------------------------
# Paper fixtures (real abstracts for deterministic assertions)
# ---------------------------------------------------------------------------

from shared.models import Paper


@pytest.fixture(scope="session")
def alphafold_paper() -> Paper:
    """2021 AlphaFold paper — high novelty, strong evidence, buildable."""
    return Paper(
        paper_id="test-alphafold-2021",
        title="Highly accurate protein structure prediction with AlphaFold",
        abstract=(
            "Proteins are essential to life, and understanding their structure is key to "
            "understanding their function. AlphaFold produces a highly accurate prediction "
            "of protein 3D structure from its amino acid sequence. We present the full open-source "
            "AlphaFold model, training procedure, model architecture using novel neural network "
            "components, and an inference pipeline that predicts structures of single proteins "
            "and protein complexes. We demonstrate state-of-the-art accuracy on CASP14 "
            "benchmarks including the most challenging free-modelling targets. "
            "We provide evaluation of our results on diverse test sets. "
            "The open-source code, model weights, and a database of predictions for the "
            "human proteome and key organisms are freely available."
        ),
        year=2021,
        venue="Nature",
        citation_count=12000,
        is_open_access=True,
        fields_of_study=["Computational Biology", "Machine Learning", "Structural Biology"],
        source="semantic_scholar",
    )


@pytest.fixture(scope="session")
def crispr_paper() -> Paper:
    """CRISPR therapeutic paper — strong biotech/IP signals."""
    return Paper(
        paper_id="test-crispr-therapeutics",
        title="CRISPR-Cas9 for medical genetic screens: analysis of germline mutation in mice",
        abstract=(
            "The CRISPR-Cas9 system is a powerful genome editing tool that has been widely adopted "
            "for research and shows great promise for therapeutic applications. We present a "
            "novel implementation of CRISPR-Cas9 delivery via lipid nanoparticles for "
            "in vivo gene correction. Our prototype system demonstrated 80% editing efficiency "
            "in mouse liver cells with minimal off-target effects measured by whole-genome "
            "sequencing. Results show significant improvement over prior delivery methods. "
            "The system is fabricated using proprietary lipid formulations. "
            "Benchmarks against leading approaches confirm competitive performance."
        ),
        year=2022,
        venue="Nature Medicine",
        citation_count=850,
        is_open_access=False,
        fields_of_study=["Genomics", "Therapeutic", "Gene Editing"],
        source="semantic_scholar",
    )


@pytest.fixture(scope="session")
def position_paper() -> Paper:
    """Vision/position paper — should score low, high conceptual penalty."""
    return Paper(
        paper_id="test-position-paper",
        title="Toward a theoretical framework for understanding AI safety: a vision paper",
        abstract=(
            "We envision a future where artificial intelligence systems are aligned with human "
            "values. In this position paper, we propose a theoretical framework for understanding "
            "the long-term trajectory of AI development. We believe that it is possible that "
            "current approaches could potentially lead to misaligned systems. Future work should "
            "investigate these hypotheses. We speculate about the role of interpretability "
            "research and envision new regulatory structures that might enable safer AI. "
            "This paper outlines our perspective on these challenges without presenting "
            "empirical results or implementation details."
        ),
        year=2023,
        venue="Workshop on AI Safety",
        citation_count=12,
        is_open_access=True,
        fields_of_study=["AI Safety", "Philosophy"],
        source="semantic_scholar",
    )


@pytest.fixture(scope="session")
def workshop_paper() -> Paper:
    """Minimal-evidence workshop abstract."""
    return Paper(
        paper_id="test-workshop-toy",
        title="Preliminary exploration of attention mechanisms in small language models",
        abstract=(
            "We present preliminary results on attention mechanism variants in small-scale "
            "language models. Our toy experiment on a subset of the Penn Treebank shows "
            "marginal improvements. We hope to extend this work in future research."
        ),
        year=2023,
        venue="NeurIPS Workshop",
        citation_count=3,
        is_open_access=True,
        fields_of_study=["Natural Language Processing"],
        source="semantic_scholar",
    )


@pytest.fixture(scope="session")
def lidar_hardware_paper() -> Paper:
    """Hardware paper with prototype — should score well on buildability."""
    return Paper(
        paper_id="test-lidar-hardware",
        title="Solid-state LiDAR with MEMS scanning for autonomous vehicle perception",
        abstract=(
            "We present a novel solid-state LiDAR system using MEMS scanning mirrors for "
            "autonomous vehicle perception. Our prototype achieves 200m range with 0.1 degree "
            "angular resolution. The fabricated system demonstrates state-of-the-art performance "
            "on the KITTI benchmark. Hardware implementation uses proprietary MEMS fabrication "
            "process with demonstrated manufacturing yield of 85%. Deployed in field trials "
            "with 3 automotive partners. The system architecture combines novel optical design "
            "with custom ASIC for real-time processing. Results outperform competing solid-state "
            "approaches on range, resolution, and cost."
        ),
        year=2022,
        venue="IEEE Sensors",
        citation_count=320,
        is_open_access=False,
        fields_of_study=["Sensors", "Autonomous Vehicles", "Photonics"],
        source="semantic_scholar",
    )


# ---------------------------------------------------------------------------
# Real papers from Semantic Scholar (session-scoped, fetched once)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def alphafold_s2_papers():
    """Fetch real AlphaFold papers from Semantic Scholar (requires internet)."""
    try:
        from papers_mcp.semantic_scholar import SemanticScholarClient
        client = SemanticScholarClient()
        papers = client.search("AlphaFold protein structure prediction", limit=10)
        return papers
    except Exception as e:
        pytest.skip(f"Could not fetch papers from Semantic Scholar: {e}")
