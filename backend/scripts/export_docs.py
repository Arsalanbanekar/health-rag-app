"""
Export the ingested corpus to services/local_documents.json.

This file is the offline fallback used by supabase_client.get_all_documents()
when Supabase is unreachable. It holds no embeddings — only the text and the
metadata the UI needs to render a source.

Run after seed_database.py so the fallback matches what is actually indexed.

Usage:
    python scripts/export_docs.py
    python scripts/export_docs.py --no-cache
"""
import argparse
import json
import os
import sys

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.ingestion.manifest import DEFAULT_MANIFEST_PATH, load_manifest
from services.ingestion.pipeline import build_documents

TARGET_PATH = os.path.join(os.path.dirname(__file__), "..", "services", "local_documents.json")


def export(manifest_path: str = DEFAULT_MANIFEST_PATH, use_cache: bool = True) -> None:
    manifest = load_manifest(manifest_path)

    errors = manifest.validate()
    if errors:
        print("Manifest validation failed:")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)

    rows, stats = build_documents(manifest, use_cache=use_cache)
    if not rows:
        print("No documents produced — nothing exported.")
        sys.exit(1)

    for i, row in enumerate(rows):
        row["id"] = f"local-doc-{i+1}"

    os.makedirs(os.path.dirname(TARGET_PATH), exist_ok=True)
    with open(TARGET_PATH, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)

    print(f"Successfully exported {len(rows)} documents to {os.path.abspath(TARGET_PATH)}")
    if stats.sources_failed:
        print(f"⚠️  {stats.sources_failed} source(s) failed during ingestion.")


def main():
    parser = argparse.ArgumentParser(description="Export the corpus for offline fallback.")
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST_PATH, help="Path to manifest.json")
    parser.add_argument("--no-cache", action="store_true", help="Re-download source pages")
    args = parser.parse_args()

    export(manifest_path=args.manifest, use_cache=not args.no_cache)


if __name__ == "__main__":
    main()
