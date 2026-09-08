"""
Ingestion Package
Turns published health fact sheets into chunked, tagged, embedding-ready rows
for the medical_documents knowledge base.

Flow: manifest -> fetch (cached) -> parse sections -> chunk -> tag -> rows.
"""
from services.ingestion.chunker import Chunk, Section, chunk_sections, split_sentences
from services.ingestion.fetchers import FetchedPage, fetch_page, parse_sections
from services.ingestion.manifest import Manifest, SourceSpec, load_manifest
from services.ingestion.pipeline import IngestionStats, build_documents
from services.ingestion.tagger import extract_tags, validate_vocabulary
from services.ingestion.taxonomy import (
    VALID_CATEGORIES,
    VALID_SOURCE_TYPES,
    VALID_TOPICS,
    category_from_heading,
)

__all__ = [
    "Chunk",
    "Section",
    "chunk_sections",
    "split_sentences",
    "FetchedPage",
    "fetch_page",
    "parse_sections",
    "Manifest",
    "SourceSpec",
    "load_manifest",
    "IngestionStats",
    "build_documents",
    "extract_tags",
    "validate_vocabulary",
    "VALID_TOPICS",
    "VALID_CATEGORIES",
    "VALID_SOURCE_TYPES",
    "category_from_heading",
]
