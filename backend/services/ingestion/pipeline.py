"""
Ingestion Pipeline
Manifest -> fetch -> parse sections -> chunk -> tag -> rows ready for Supabase.

Output rows use exactly the existing medical_documents columns; nothing here
changes the metadata schema.
"""
import logging
from dataclasses import dataclass
from typing import Any, Dict, List

from services.ingestion.chunker import chunk_sections
from services.ingestion.fetchers import fetch_page
from services.ingestion.manifest import Manifest, SourceSpec
from services.ingestion.tagger import extract_tags
from services.ingestion.taxonomy import category_from_heading, category_from_text

logger = logging.getLogger(__name__)

# Headings the parser assigns when a page has no structure of its own.
_GENERIC_HEADINGS = {"overview", "summary", "introduction", ""}

MAX_SUBTOPIC_LENGTH = 120


@dataclass
class IngestionStats:
    sources_processed: int = 0
    sources_failed: int = 0
    pages_from_cache: int = 0
    sections_parsed: int = 0
    chunks_produced: int = 0


def _build_subtopic(spec: SourceSpec, page_title: str, heading: str) -> str:
    """
    Compose a non-empty subtopic (the column is NOT NULL).

    Prefers "<page> — <section>" so a retrieved chunk names both the fact sheet
    it came from and the section within it.
    """
    prefix = spec.subtopic_prefix or page_title or spec.topic
    is_generic = heading.strip().lower() in _GENERIC_HEADINGS

    subtopic = prefix if is_generic else f"{prefix} — {heading}"
    subtopic = " ".join(subtopic.split())

    if len(subtopic) > MAX_SUBTOPIC_LENGTH:
        subtopic = subtopic[: MAX_SUBTOPIC_LENGTH - 1].rstrip() + "…"
    return subtopic or spec.topic


def _resolve_category(spec: SourceSpec, heading: str, text: str) -> str:
    """
    Category resolution order: heading pattern -> content keywords -> the
    source's declared default. Real MedlinePlus headings are natural questions
    ("What causes long-term stress?"), which the heading patterns mostly catch;
    content scoring is the backstop for the ones that don't ("What is X?").
    """
    if not spec.infer_category_from_heading:
        return spec.category

    inferred = category_from_heading(heading)
    if inferred:
        return inferred

    inferred = category_from_text(text)
    if inferred:
        return inferred

    return spec.category


def build_documents(manifest: Manifest, use_cache: bool = True) -> tuple[List[Dict[str, Any]], IngestionStats]:
    """
    Turn every manifest source into chunked, tagged document rows.

    A source that fails to fetch or parse is logged and skipped rather than
    aborting the run — one dead URL should not cost you the whole corpus.
    """
    rows: List[Dict[str, Any]] = []
    stats = IngestionStats()

    for spec in manifest.sources:
        try:
            page = fetch_page(spec.url, use_cache=use_cache, fallback_title=spec.subtopic_prefix)
        except Exception as e:
            stats.sources_failed += 1
            logger.error(f"Failed to fetch {spec.url}: {e}")
            continue

        if not page.sections:
            stats.sources_failed += 1
            logger.error(
                f"No content parsed from {spec.url}. If this is a MedlinePlus "
                f"page, it may genuinely carry no summary of its own (a pure "
                f"category-index page one level above real content) — check "
                f"the page in a browser before assuming this is a bug."
            )
            continue

        if page.from_cache:
            stats.pages_from_cache += 1
        stats.sections_parsed += len(page.sections)

        chunks = chunk_sections(
            page.sections,
            chunk_tokens=manifest.chunk_tokens,
            overlap_tokens=manifest.overlap_tokens,
        )

        if not chunks:
            stats.sources_failed += 1
            logger.error(f"Parsed {spec.url} but produced 0 chunks.")
            continue

        for chunk in chunks:
            category = _resolve_category(spec, chunk.heading, chunk.text)

            tags = extract_tags(chunk.text, spec.topic, heading=chunk.heading)
            for extra in spec.extra_tags:
                normalized = extra.strip().lower()
                if normalized and normalized not in tags:
                    tags.append(normalized)

            rows.append(
                {
                    "topic": spec.topic,
                    "subtopic": _build_subtopic(spec, page.title, chunk.heading),
                    "content": chunk.text,
                    "category": category,
                    "tags": tags,
                    "source_type": spec.source_type,
                    "source": spec.url,
                    "credibility_score": spec.credibility_score,
                    "evidence_level": spec.evidence_level,
                }
            )

        stats.chunks_produced += len(chunks)
        stats.sources_processed += 1
        logger.info(f"{spec.url}: {len(page.sections)} sections -> {len(chunks)} chunks")

    return rows, stats
