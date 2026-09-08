"""
Vector Search Module
Runs dense semantic search queries using Postgres pgvector cosine distance metrics.
"""
import logging
from typing import List, Dict, Any, Optional
from services.supabase_client import get_supabase

logger = logging.getLogger(__name__)

def execute_vector_search(
    query_embedding: List[float],
    filter_category: Optional[str] = None,
    filter_tags: Optional[List[str]] = None,
    match_count: int = 6,
    threshold: float = 0.35
) -> List[Dict[str, Any]]:
    """
    Sends the vector query and optional metadata filters to the Supabase RPC.
    """
    try:
        client = get_supabase()
        
        rpc_params = {
            "query_embedding": query_embedding,
            "match_threshold": threshold,
            "match_count": match_count
        }
        
        if filter_category:
            rpc_params["filter_category"] = filter_category
        if filter_tags:
            rpc_params["filter_tags"] = filter_tags

        logger.info(f"Invoking Supabase match_medical_documents RPC with params: "
                    f"category={filter_category}, tags={filter_tags}, count={match_count}")
        
        response = client.rpc("match_medical_documents", rpc_params).execute()
        return response.data or []
        
    except Exception as e:
        logger.error(f"Postgres/pgvector similarity search failed: {e}")
        return []
