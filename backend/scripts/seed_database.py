"""
Hybrid RAG — Database Seeding Script
Ingests real fact sheets from the source manifest, chunks them to the embedding
model's context window, generates 384-dim embeddings, validates everything, and
populates Supabase with metadata for hybrid retrieval.

Usage:
    python scripts/seed_database.py                # ingest, embed, insert
    python scripts/seed_database.py --dry-run      # chunk + report, no DB write
    python scripts/seed_database.py --no-cache     # re-download source pages
    python scripts/seed_database.py --manifest PATH
"""
import argparse
import os
import sys
import time
from collections import Counter
from typing import Any, Dict, List

# Fix Windows terminal Unicode issues
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Add parent dir to path so we can import services
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from services.embeddings import (
    EMBEDDING_DIM,
    MAX_CONTENT_TOKENS,
    MODEL_NAME,
    count_tokens,
    embed_passages,
    load_model,
)
from services.ingestion.manifest import DEFAULT_MANIFEST_PATH, load_manifest
from services.ingestion.pipeline import build_documents
from services.ingestion.tagger import validate_vocabulary
from services.ingestion.taxonomy import (
    VALID_CATEGORIES,
    VALID_SOURCE_TYPES,
    VALID_TOPICS,
)
from services.supabase_client import get_supabase

EXPECTED_EMBEDDING_DIM = EMBEDDING_DIM

# Rows per insert request. Supabase handles batches comfortably at this size;
# one request per row is needlessly slow once you are seeding hundreds of chunks.
INSERT_BATCH_SIZE = 100


# ────────────────────────────────────────────────────────────
# VALIDATION HELPERS
# ────────────────────────────────────────────────────────────

def validate_document(doc: dict, index: int) -> List[str]:
    """Validate a single document against the approved taxonomy. Returns list of errors."""
    errors = []
    if doc.get("topic") not in VALID_TOPICS:
        errors.append(f"Invalid topic: '{doc.get('topic')}'. Must be one of {sorted(VALID_TOPICS)}")
    if doc.get("category") not in VALID_CATEGORIES:
        errors.append(f"Invalid category: '{doc.get('category')}'. Must be one of {sorted(VALID_CATEGORIES)}")
    if doc.get("source_type") not in VALID_SOURCE_TYPES:
        errors.append(f"Invalid source_type: '{doc.get('source_type')}'. Must be one of {sorted(VALID_SOURCE_TYPES)}")
    if not doc.get("subtopic"):
        errors.append("Missing subtopic")
    if not doc.get("content"):
        errors.append("Missing content")
    if not isinstance(doc.get("tags"), list) or len(doc["tags"]) == 0:
        errors.append("Tags must be a non-empty list")

    tokens = count_tokens(doc.get("content", ""))
    if tokens > MAX_CONTENT_TOKENS:
        errors.append(
            f"Content is {tokens} tokens, over the model's {MAX_CONTENT_TOKENS} limit "
            f"— it would be silently truncated at embed time"
        )
    return errors


def validate_embedding(embedding, index: int, subtopic: str) -> List[str]:
    """Validate a single embedding vector. Returns list of errors."""
    errors = []
    if not isinstance(embedding, list):
        errors.append(f"Embedding is {type(embedding).__name__}, expected list")
    elif len(embedding) != EXPECTED_EMBEDDING_DIM:
        errors.append(f"Embedding dim={len(embedding)}, expected {EXPECTED_EMBEDDING_DIM}")
    elif not all(isinstance(v, float) for v in embedding):
        errors.append("Embedding contains non-float values")
    return errors


def print_corpus_report(rows: List[Dict[str, Any]]) -> None:
    """Summarize what was chunked, so problems are visible before any DB write."""
    token_counts = [count_tokens(r["content"]) for r in rows]
    by_topic = Counter(r["topic"] for r in rows)
    by_category = Counter(r["category"] for r in rows)
    by_source_type = Counter(r["source_type"] for r in rows)

    print(f"\n  Chunks:      {len(rows)}")
    if token_counts:
        ordered = sorted(token_counts)
        print(f"  Tokens:      min {ordered[0]} | median {ordered[len(ordered)//2]} | max {ordered[-1]}")
        print(f"  Total:       {sum(token_counts):,} tokens")

    print("\n  By topic:")
    for topic, n in by_topic.most_common():
        print(f"    {n:>4}  {topic}")

    print("\n  By category:")
    for category, n in by_category.most_common():
        print(f"    {n:>4}  {category}")

    print("\n  By source type:")
    for source_type, n in by_source_type.most_common():
        print(f"    {n:>4}  {source_type}")

    # A topic whose chunks all landed in one category means heading inference
    # is not firing — worth seeing before you seed.
    thin = [t for t, n in by_topic.items() if n < 3]
    if thin:
        print(f"\n  ⚠️  Thin coverage (<3 chunks): {', '.join(sorted(thin))}")


def insert_in_batches(client, rows: List[Dict[str, Any]]) -> tuple[int, int]:
    """Insert rows in batches. Returns (succeeded, failed)."""
    succeeded = 0
    failed = 0

    for start in range(0, len(rows), INSERT_BATCH_SIZE):
        batch = rows[start:start + INSERT_BATCH_SIZE]
        try:
            client.table("medical_documents").insert(batch).execute()
            succeeded += len(batch)
            print(f"  ✓ [{succeeded:>4}/{len(rows)}] batch of {len(batch)} inserted")
        except Exception as e:
            failed += len(batch)
            print(f"  ✗ batch at offset {start} failed: {e}")

    return succeeded, failed


# ────────────────────────────────────────────────────────────
# SEED FUNCTION
# ────────────────────────────────────────────────────────────

def seed(manifest_path: str = DEFAULT_MANIFEST_PATH, use_cache: bool = True, dry_run: bool = False):
    """Ingest, chunk, validate, embed, and insert all source documents."""
    print(f"\n{'='*60}")
    print("  HYBRID RAG — DATABASE SEEDING")
    print(f"  Model: {MODEL_NAME} ({EMBEDDING_DIM}-dim, {MAX_CONTENT_TOKENS} usable tokens)")
    if dry_run:
        print("  MODE:  DRY RUN — nothing will be written to Supabase")
    print(f"{'='*60}\n")

    # ── Step 0: Check the tagger still agrees with the retrieval filters ──
    print("[1/6] Checking tag vocabulary against retrieval filters...")
    vocab_errors = validate_vocabulary()
    if vocab_errors:
        print("  ✗ Tag vocabulary is inconsistent with metadata_filter.TOPIC_TO_TAGS_MAP:")
        for err in vocab_errors:
            print(f"    - {err}")
        print("\n[ABORT] Seeding now would produce chunks that filtered search cannot find.")
        return
    print("  ✓ Anchor tags all match the retrieval filters.\n")

    # ── Step 1: Load and validate the manifest ──
    print("[2/6] Loading source manifest...")
    try:
        manifest = load_manifest(manifest_path)
    except FileNotFoundError as e:
        print(f"  ✗ {e}")
        return

    manifest_errors = manifest.validate()
    if manifest_errors:
        print("  ✗ Manifest validation failed:")
        for err in manifest_errors:
            print(f"    - {err}")
        print("\n[ABORT] Fix the manifest before seeding.")
        return
    print(f"  ✓ {len(manifest.sources)} sources | chunk={manifest.chunk_tokens} "
          f"overlap={manifest.overlap_tokens}\n")

    # ── Step 2: Fetch, parse and chunk ──
    print("[3/6] Fetching and chunking sources...")
    start = time.time()
    rows, stats = build_documents(manifest, use_cache=use_cache)
    print(f"  ✓ {stats.sources_processed} sources -> {stats.sections_parsed} sections "
          f"-> {stats.chunks_produced} chunks in {time.time() - start:.1f}s")
    if stats.pages_from_cache:
        print(f"  ℹ️  {stats.pages_from_cache} page(s) served from local cache")
    if stats.sources_failed:
        print(f"  ⚠️  {stats.sources_failed} source(s) failed — see log output above")

    if not rows:
        print("\n[ABORT] No chunks produced.")
        return

    print_corpus_report(rows)

    # ── Step 3: Validate every chunk against the taxonomy ──
    print("\n[4/6] Validating chunks against taxonomy...")
    all_valid = True
    for i, doc in enumerate(rows):
        errs = validate_document(doc, i)
        if errs:
            all_valid = False
            print(f"  ✗ Chunk {i+1} ({doc.get('subtopic', '?')}):")
            for e in errs:
                print(f"    {e}")

    if not all_valid:
        print("\n[ABORT] Fix validation errors above before seeding.")
        return
    print(f"  ✓ All {len(rows)} chunks pass taxonomy and length validation.\n")

    if dry_run:
        print(f"{'='*60}")
        print("  DRY RUN COMPLETE — no embeddings generated, nothing written.")
        print(f"{'='*60}\n")
        return

    # ── Step 4: Load model & generate embeddings ──
    print("[5/6] Loading embedding model...")
    start = time.time()
    load_model()
    print(f"  ✓ Model loaded in {time.time() - start:.1f}s")

    print(f"  Generating {len(rows)} embeddings...")
    start = time.time()
    try:
        embeddings = embed_passages([r["content"] for r in rows])
    except Exception as e:
        print(f"  ✗ Embedding failed: {e}")
        print("\n[ABORT] Existing knowledge base left untouched.")
        return
    print(f"  ✓ Generated {len(embeddings)} embeddings in {time.time() - start:.1f}s")

    embed_valid = True
    for i, (emb, doc) in enumerate(zip(embeddings, rows)):
        errs = validate_embedding(emb, i, doc["subtopic"])
        if errs:
            embed_valid = False
            print(f"  ✗ Embedding {i+1} ({doc['subtopic']}):")
            for e in errs:
                print(f"    {e}")

    if not embed_valid:
        print("\n[ABORT] Embedding validation failed. Knowledge base left untouched.")
        return

    print(f"  ✓ Dimension: {len(embeddings[0])} | Sample: {embeddings[0][:3]}\n")

    for row, embedding in zip(rows, embeddings):
        row["embedding"] = embedding

    # ── Step 5: Replace the knowledge base ──
    # Deletion happens only now, after embeddings are proven good, so a failure
    # earlier in the run cannot leave the app with an empty knowledge base.
    print("[6/6] Writing to Supabase...")
    client = get_supabase()

    try:
        print("  [*] Cleaning existing documents from medical_documents...")
        client.table("medical_documents").delete().neq(
            "id", "00000000-0000-0000-0000-000000000000"
        ).execute()
        print("  ✓ Cleaned successfully.")
    except Exception as e:
        print(f"  ⚠️ Could not clean table (might be empty): {e}")

    success, errors = insert_in_batches(client, rows)

    # ── Summary ──
    print(f"\n{'='*60}")
    print("  SEEDING COMPLETE")
    print(f"  Inserted: {success}/{len(rows)}")
    print(f"  Errors:   {errors}")
    print(f"{'='*60}")

    if errors == 0:
        print("  🚀 Knowledge base ready for Hybrid RAG queries!")
        if success >= 100:
            print("  ℹ️  You now have 100+ rows — enable the IVFFlat index in")
            print("     supabase_schema.sql (last line) for faster vector search.")
    else:
        print("  ⚠️  Some chunks failed. Check errors above.")
    print()


def main():
    parser = argparse.ArgumentParser(description="Seed the medical knowledge base.")
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST_PATH, help="Path to manifest.json")
    parser.add_argument("--no-cache", action="store_true", help="Re-download source pages")
    parser.add_argument("--dry-run", action="store_true", help="Chunk and report without writing")
    args = parser.parse_args()

    seed(manifest_path=args.manifest, use_cache=not args.no_cache, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
