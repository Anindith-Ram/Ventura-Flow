"""Load/save the VC profile — persisted globally at ~/.research_pipeline/vc_profile.json."""

from __future__ import annotations

import json
import logging
from datetime import datetime

from shared.config import settings
from shared.models import VCProfile

logger = logging.getLogger(__name__)


# Built-in presets so a VC can start from a template instead of a blank form.
TEMPLATES: dict[str, VCProfile] = {
    "Deep Tech": VCProfile(
        template="Deep Tech",
        thesis=(
            "We back early-stage companies commercialising breakthrough scientific research "
            "with strong technical moats, defensible IP, and a credible path from lab to product."
        ),
        sectors=["semiconductors", "robotics", "quantum", "advanced manufacturing", "materials"],
        stage="seed",
        geography=["US", "EU", "UK"],
        weight_vc_fit=0.45, weight_novelty=0.35, weight_author_credibility=0.20,
        min_h_index=5,
    ),
    "Climate": VCProfile(
        template="Climate",
        thesis=(
            "Scalable climate solutions addressing decarbonisation, carbon removal, energy transition, "
            "or climate adaptation with clear unit-economics and defensible technology."
        ),
        sectors=["carbon capture", "energy storage", "clean energy", "climate adaptation", "sustainable materials"],
        stage="seed",
        weight_vc_fit=0.50, weight_novelty=0.30, weight_author_credibility=0.20,
    ),
    "Bio / Health": VCProfile(
        template="Bio / Health",
        thesis=(
            "Novel therapeutics, diagnostics, platform biology, or digital health with strong "
            "scientific evidence, credible development path, and regulatory viability."
        ),
        sectors=["therapeutics", "diagnostics", "synthetic biology", "digital health", "medical devices"],
        stage="seed",
        weight_vc_fit=0.40, weight_novelty=0.30, weight_author_credibility=0.30,
        min_h_index=10,
    ),
    "AI Infra": VCProfile(
        template="AI Infra",
        thesis=(
            "Infrastructure, tooling, and foundational research that makes AI systems faster, cheaper, "
            "more reliable, or more capable — from training to inference to deployment."
        ),
        sectors=["ml systems", "inference optimisation", "agentic systems", "evaluation", "training infrastructure"],
        stage="seed",
        weight_vc_fit=0.50, weight_novelty=0.35, weight_author_credibility=0.15,
    ),
}


def load_profile() -> VCProfile:
    """Return the saved profile, or an empty default."""
    path = settings.vc_profile_path
    if not path.exists():
        logger.info("No VC profile at %s — returning empty default", path)
        return VCProfile()
    try:
        data = json.loads(path.read_text())
        return VCProfile.model_validate(data)
    except Exception as exc:
        logger.warning("Failed to load VC profile (%s); returning empty", exc)
        return VCProfile()


def save_profile(profile: VCProfile) -> None:
    profile.updated_at = datetime.utcnow()
    path = settings.vc_profile_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile.model_dump(mode="json"), indent=2, default=str))
    logger.info("Saved VC profile to %s", path)
