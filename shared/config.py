"""Centralised settings loaded from environment / .env file."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (two levels up from this file).
_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / ".env", override=False)


class Settings:
    """All runtime configuration values."""

    # ── API keys ──────────────────────────────────────────────────────────────
    s2_api_key: str
    openalex_email: str

    # ── Embeddings ───────────────────────────────────────────────────────────
    embedding_backend: str   # "fastembed" | "openai"
    embedding_model: str
    embedding_dim: int
    openai_api_key: str
    openai_base_url: str
    openai_embedding_model: str
    openai_scoring_model: str

    # ── Vector store ─────────────────────────────────────────────────────────
    qdrant_url: str
    qdrant_api_key: str
    qdrant_collection: str

    # ── Structured storage ───────────────────────────────────────────────────
    db_path: str

    # ── Pipeline behaviour ───────────────────────────────────────────────────
    ocr_score_threshold: float
    ocr_max_pages: int
    paper_pass_threshold: float
    pdf_download_dir: str
    paddleocr_command: str

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: str
    log_dir: str

    def __init__(self) -> None:
        self.s2_api_key = os.getenv("S2_API_KEY", "")
        self.openalex_email = os.getenv("OPENALEX_EMAIL", "research-intelligence@example.com")

        self.embedding_backend = os.getenv("EMBEDDING_BACKEND", "fastembed")
        self.embedding_model = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
        self.embedding_dim = int(os.getenv("EMBEDDING_DIM", "384"))
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")
        self.openai_base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.openai_embedding_model = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
        self.openai_scoring_model = os.getenv("OPENAI_SCORING_MODEL", "gpt-4.1-mini")

        self.qdrant_url = os.getenv("QDRANT_URL", "")
        self.qdrant_api_key = os.getenv("QDRANT_API_KEY", "")
        self.qdrant_collection = os.getenv("QDRANT_COLLECTION", "papers")

        self.db_path = os.getenv("DB_PATH", str(_ROOT / "data" / "papers.db"))

        self.ocr_score_threshold = float(os.getenv("OCR_SCORE_THRESHOLD", "0.6"))
        self.ocr_max_pages = int(os.getenv("OCR_MAX_PAGES", "0"))
        self.paper_pass_threshold = float(os.getenv("PAPER_PASS_THRESHOLD", "0.65"))
        self.pdf_download_dir = os.getenv("PDF_DOWNLOAD_DIR", str(_ROOT / "data" / "pdfs"))
        self.paddleocr_command = os.getenv("PADDLEOCR_COMMAND", "paddleocr_mcp")

        self.log_level = os.getenv("LOG_LEVEL", "INFO")
        self.log_dir = os.getenv("LOG_DIR", str(_ROOT / "logs"))

        # Ensure directories exist.
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.pdf_download_dir).mkdir(parents=True, exist_ok=True)
        Path(self.log_dir).mkdir(parents=True, exist_ok=True)


# Module-level singleton — import and reuse everywhere.
settings = Settings()
