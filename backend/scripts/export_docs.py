import os
import json
import sys

# Add path to load seed_database
sys.path.insert(0, os.path.dirname(__file__))

from seed_database import MEDICAL_DOCS

target_path = os.path.join(os.path.dirname(__file__), "..", "services", "local_documents.json")

# Add auto-generated IDs to documents if not present
for i, doc in enumerate(MEDICAL_DOCS):
    doc["id"] = f"local-doc-{i+1}"

with open(target_path, "w", encoding="utf-8") as f:
    json.dump(MEDICAL_DOCS, f, indent=2, ensure_ascii=False)

print(f"Successfully exported {len(MEDICAL_DOCS)} documents to {target_path}")
