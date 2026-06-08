"""
Keyword-based Retrieval Service (Vectorless RAG)
Replaces HuggingFace vector embeddings with BM25-style keyword/chunk matching.
No GPU, no model download, no vector DB calls needed.
"""
import logging
import re
from typing import List

logger = logging.getLogger(__name__)


def tokenize(text: str) -> List[str]:
    """Lowercase and tokenize text into individual words."""
    return re.findall(r'\b\w+\b', text.lower())


def compute_keyword_score(query: str, document_text: str) -> float:
    """
    Simple keyword overlap score (BM25-inspired, unweighted).
    Returns a normalized float between 0.0 and 1.0.
    """
    query_tokens = set(tokenize(query))
    doc_tokens = set(tokenize(document_text))

    if not query_tokens or not doc_tokens:
        return 0.0

    overlap = query_tokens & doc_tokens
    # Jaccard-style overlap with query coverage bias
    score = len(overlap) / (len(query_tokens) + 0.5 * len(doc_tokens - query_tokens) + 1e-9)
    return min(score, 1.0)


def rank_documents_by_keyword(query: str, documents: List[dict], top_k: int = 6, threshold: float = 0.05) -> List[dict]:
    """
    Given a query and a list of document dicts (with a 'content' field),
    return the top_k most keyword-relevant documents above the threshold.
    Adds a 'similarity' field to each returned doc for compatibility.
    """
    scored = []
    for doc in documents:
        content = doc.get("content", "")
        topic = doc.get("topic", "")
        subtopic = doc.get("subtopic", "")
        # Score against content + topic tags for better matching
        combined = f"{topic} {subtopic} {content}"
        score = compute_keyword_score(query, combined)
        if score >= threshold:
            scored.append({**doc, "similarity": round(score, 4)})

    scored.sort(key=lambda x: x["similarity"], reverse=True)
    return scored[:top_k]


# --- Backward-compatibility stubs (so main.py doesn't break on import) ---

def load_model():
    """No-op stub — kept for backward compatibility with main.py startup."""
    logger.info("Vectorless mode: no embedding model needed.")
    return None


def embed_text(text: str) -> List[float]:
    """Stub — not used in vectorless mode. Returns empty list."""
    return []


def embed_batch(texts: List[str]) -> List[List[float]]:
    """Stub — not used in vectorless mode. Returns empty list."""
    return [[] for _ in texts]
