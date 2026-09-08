"""
Source Manifest
Declares which pages to ingest and what metadata their chunks inherit.

Everything the taxonomy needs but a web page cannot tell us — topic, default
category, source type, credibility — is declared here explicitly rather than
guessed from page content. Guessing a credibility score is how a consumer fact
sheet ends up labelled as a systematic review.
"""
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from services.ingestion.taxonomy import (
    DEFAULT_CREDIBILITY,
    VALID_CATEGORIES,
    VALID_SOURCE_TYPES,
    VALID_TOPICS,
)

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data", "sources")
DEFAULT_MANIFEST_PATH = os.path.join(DATA_DIR, "manifest.json")


@dataclass
class SourceSpec:
    """One page to ingest, with the metadata its chunks inherit."""
    url: str
    topic: str
    category: str
    source_type: str = "government_health_portal"
    credibility_score: Optional[float] = None
    evidence_level: Optional[str] = None
    publisher: str = ""
    subtopic_prefix: str = ""
    # Per-source escape hatches
    infer_category_from_heading: bool = True
    extra_tags: List[str] = field(default_factory=list)

    def __post_init__(self):
        if self.credibility_score is None:
            self.credibility_score = DEFAULT_CREDIBILITY.get(self.source_type, 0.85)
        if self.evidence_level is None:
            self.evidence_level = self.source_type

    def validate(self) -> List[str]:
        """Return taxonomy errors for this entry."""
        errors = []
        if not self.url:
            errors.append("Missing url")
        if self.topic not in VALID_TOPICS:
            errors.append(f"Invalid topic '{self.topic}'. Must be one of {sorted(VALID_TOPICS)}")
        if self.category not in VALID_CATEGORIES:
            errors.append(
                f"Invalid category '{self.category}'. Must be one of {sorted(VALID_CATEGORIES)}"
            )
        if self.source_type not in VALID_SOURCE_TYPES:
            errors.append(
                f"Invalid source_type '{self.source_type}'. "
                f"Must be one of {sorted(VALID_SOURCE_TYPES)}"
            )
        if not (0.0 <= float(self.credibility_score) <= 1.0):
            errors.append(f"credibility_score {self.credibility_score} outside 0.0-1.0")
        return errors


@dataclass
class Manifest:
    sources: List[SourceSpec]
    chunk_tokens: int = 512
    overlap_tokens: int = 50

    def validate(self) -> List[str]:
        errors: List[str] = []
        if not self.sources:
            errors.append("Manifest contains no sources.")

        seen = set()
        for i, spec in enumerate(self.sources):
            for err in spec.validate():
                errors.append(f"sources[{i}] ({spec.url or '?'}): {err}")
            if spec.url in seen:
                errors.append(f"sources[{i}]: duplicate url {spec.url}")
            seen.add(spec.url)

        if self.overlap_tokens >= self.chunk_tokens:
            errors.append(
                f"overlap_tokens ({self.overlap_tokens}) must be less than "
                f"chunk_tokens ({self.chunk_tokens})."
            )
        return errors


def load_manifest(path: str = DEFAULT_MANIFEST_PATH) -> Manifest:
    """
    Read the manifest. Per-source values override the `defaults` block.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"No manifest at {path}. Copy manifest.example.json to manifest.json "
            f"and list your source URLs."
        )

    with open(path, "r", encoding="utf-8") as f:
        raw: Dict[str, Any] = json.load(f)

    defaults: Dict[str, Any] = raw.get("defaults", {})
    sources: List[SourceSpec] = []

    for entry in raw.get("sources", []):
        merged = {**defaults, **entry}
        known = {f for f in SourceSpec.__dataclass_fields__}
        unknown = set(merged) - known
        if unknown:
            logger.warning(f"Ignoring unknown manifest keys for {merged.get('url')}: {sorted(unknown)}")
        sources.append(SourceSpec(**{k: v for k, v in merged.items() if k in known}))

    return Manifest(
        sources=sources,
        chunk_tokens=raw.get("chunk_tokens", 512),
        overlap_tokens=raw.get("overlap_tokens", 50),
    )
