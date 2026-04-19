"""Centralised settings loaded from environment / .env file."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / ".env", override=False)


class Settings:
    """All runtime configuration values."""

    def __init__(self) -> None:
        # ── OpenAlex ──────────────────────────────────────────────────────────
        self.openalex_email = os.getenv("OPENALEX_EMAIL", "research-intelligence@example.com")

        # ── Embeddings (local only) ──────────────────────────────────────────
        self.embedding_model = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
        self.embedding_dim = int(os.getenv("EMBEDDING_DIM", "384"))

        # ── Ollama models ────────────────────────────────────────────────────
        self.researcher_model = os.getenv("RESEARCHER_MODEL", "qwen3:8b")
        self.analyst_model = os.getenv("ANALYST_MODEL", "deepseek-r1:14b")
        self.judge_model = os.getenv("JUDGE_MODEL", "llama3.1:8b")
        self.triage_model = os.getenv("TRIAGE_MODEL", "qwen3:8b")
        self.planner_model = os.getenv("PLANNER_MODEL", "qwen3:8b")

        # ── Storage ──────────────────────────────────────────────────────────
        self.db_path = os.getenv("DB_PATH", str(_ROOT / "data" / "papers.db"))
        self.pdf_download_dir = os.getenv("PDF_DOWNLOAD_DIR", str(_ROOT / "data" / "pdfs"))

        # ── VC profile (global, survives across runs) ────────────────────────
        default_profile = Path.home() / ".research_pipeline" / "vc_profile.json"
        self.vc_profile_path = Path(os.getenv("VC_PROFILE_PATH", str(default_profile)))
        self.vc_profile_path.parent.mkdir(parents=True, exist_ok=True)

        # ── Pipeline behaviour ───────────────────────────────────────────────
        self.triage_top_percentile = float(os.getenv("TRIAGE_TOP_PERCENTILE", "0.10"))  # top 10%
        self.triage_min_papers = int(os.getenv("TRIAGE_MIN_PAPERS", "3"))  # always keep at least N
        self.triage_max_papers = int(os.getenv("TRIAGE_MAX_PAPERS", "20"))  # cap for cost control
        self.diversity_max_per_subfield = int(os.getenv("DIVERSITY_MAX_PER_SUBFIELD", "3"))
        self.dedup_cosine_threshold = float(os.getenv("DEDUP_COSINE_THRESHOLD", "0.92"))

        # ── Autonomous mode ──────────────────────────────────────────────────
        self.autonomous_default_minutes = int(os.getenv("AUTONOMOUS_DEFAULT_MINUTES", "60"))
        self.autonomous_default_paper_cap = int(os.getenv("AUTONOMOUS_DEFAULT_PAPER_CAP", "200"))

        # ── GUI / API ────────────────────────────────────────────────────────
        self.gui_host = os.getenv("GUI_HOST", "127.0.0.1")
        self.gui_port = int(os.getenv("GUI_PORT", "8000"))

        # ── Logging ──────────────────────────────────────────────────────────
        self.log_level = os.getenv("LOG_LEVEL", "INFO")
        self.log_dir = os.getenv("LOG_DIR", str(_ROOT / "logs"))

        # ── Output artifacts ─────────────────────────────────────────────────
        self.runs_dir = Path(os.getenv("RUNS_DIR", str(_ROOT / "outputs")))

        # Ensure directories exist.
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.pdf_download_dir).mkdir(parents=True, exist_ok=True)
        Path(self.log_dir).mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
