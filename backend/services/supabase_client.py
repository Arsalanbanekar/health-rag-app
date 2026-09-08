import logging
import os
import json
from typing import List, Optional

from supabase import create_client, Client

logger = logging.getLogger(__name__)

_supabase_client: Optional[Client] = None


def get_supabase() -> Client:
    """Singleton Supabase client."""
    global _supabase_client
    if _supabase_client is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_ANON_KEY")
        if not url or not key:
            raise ValueError("SUPABASE_URL and SUPABASE_ANON_KEY must be set in .env")
        _supabase_client = create_client(url, key)
    return _supabase_client


def vector_search(query_embedding: List[float], match_count: int = 8, threshold: float = 0.4) -> List[dict]:
    """
    Search the medical knowledge base using cosine similarity (pgvector).
    Returns top matching documents sorted by relevance.
    """
    try:
        client = get_supabase()
        result = client.rpc(
            "match_medical_documents",
            {
                "query_embedding": query_embedding,
                "match_threshold": threshold,
                "match_count": match_count,
            },
        ).execute()
        return result.data or []
    except Exception as e:
        logger.error(f"Vector search error: {e}")
        return []


def insert_document(doc: dict) -> bool:
    """Insert a medical document with its embedding into Supabase."""
    try:
        client = get_supabase()
        client.table("medical_documents").insert(doc).execute()
        return True
    except Exception as e:
        logger.error(f"Insert error: {e}")
        return False


def log_query(
    query: str,
    response: str,
    in_domain: bool,
    sources: List[dict],
    session_id: str = "anonymous",
) -> None:
    """Log every query to Supabase for training data collection."""
    try:
        client = get_supabase()
        client.table("query_logs").insert(
            {
                "session_id": session_id,
                "query": query,
                "response": response,
                "in_domain": in_domain,
                "sources": sources,
            }
        ).execute()
    except Exception as e:
        logger.warning(f"Failed to log query (non-critical): {e}")


def log_out_of_domain(query: str, session_id: str = "anonymous") -> None:
    """Log out-of-domain queries separately for training expansion."""
    try:
        client = get_supabase()
        client.table("out_of_domain_queries").insert(
            {"query": query, "session_id": session_id}
        ).execute()
    except Exception as e:
        logger.warning(f"Failed to log OOD query (non-critical): {e}")


def get_documents_count() -> int:
    """Return total number of documents in the knowledge base."""
    try:
        client = get_supabase()
        result = client.table("medical_documents").select("id", count="exact").execute()
        return result.count or 0
    except Exception as e:
        # Fall back to checking local cache size on failure
        try:
            local_path = os.path.join(os.path.dirname(__file__), "local_documents.json")
            if os.path.exists(local_path):
                with open(local_path, "r", encoding="utf-8") as f:
                    return len(json.load(f))
        except Exception:
            pass
        logger.error(f"Count error: {e}")
        return 0


def get_all_documents() -> List[dict]:
    """
    Fetch all medical documents (without embeddings).
    Attempts to read from Supabase, falls back to local JSON cache on failure.
    """
    # 1. Try fetching from Supabase database
    try:
        client = get_supabase()
        result = (
            client.table("medical_documents")
            .select("id, topic, subtopic, content, source, credibility_score")
            .execute()
        )
        if result.data:
            return result.data
    except Exception as e:
        logger.warning(f"get_all_documents from Supabase failed ({e}). Falling back to local documents cache.")

    # 2. Fall back to local documents cache if Supabase is offline/unreachable
    try:
        local_path = os.path.join(os.path.dirname(__file__), "local_documents.json")
        if os.path.exists(local_path):
            with open(local_path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as local_err:
        logger.error(f"Failed to load local fallback documents: {local_err}")

    return []
