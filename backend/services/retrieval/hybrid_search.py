"""
Hybrid Search Orchestrator
Coordinates: Classification -> Embedding -> Filtered Search -> Fallback -> Format context.
"""
import logging
from typing import List, Dict, Any, Tuple

from services.embeddings import embed_query
from services.retrieval.query_classifier import classify_query
from services.retrieval.metadata_filter import build_metadata_filters
from services.retrieval.vector_search import execute_vector_search

logger = logging.getLogger(__name__)

def perform_hybrid_retrieval(query: str, top_k: int = 6) -> Tuple[List[Dict[str, Any]], str]:
    """
    Runs query analysis, applies metadata filters, triggers semantic search,
    and falls back gracefully to global search if matching subsets are empty.
    
    Returns:
        Tuple of (List of retrieved dictionaries, Formatted context string).
    """
    # 1. Classify intent
    classification = classify_query(query)
    filters = build_metadata_filters(classification)
    
    # 2. Embed query (bge is asymmetric — queries need the instruction prefix
    #    that embed_query applies; embedding a query as a passage costs recall)
    try:
        query_embedding = embed_query(query)
    except Exception as e:
        logger.error(f"Cannot generate query embedding: {e}")
        return [], ""

    # 3. Retrieve with Strict Filters (Category + Tags)
    retrieved_docs = execute_vector_search(
        query_embedding=query_embedding,
        filter_category=filters["filter_category"],
        filter_tags=filters["filter_tags"],
        match_count=top_k
    )
    
    # Fallback Step A: Relax tags filter if empty
    if not retrieved_docs and filters["filter_tags"]:
        logger.info("Category + Tags returned 0 docs. relaxing tags filter.")
        retrieved_docs = execute_vector_search(
            query_embedding=query_embedding,
            filter_category=filters["filter_category"],
            filter_tags=None,
            match_count=top_k
        )
        
    # Fallback Step B: Relax category filter (Global Semantic Search lookup)
    if not retrieved_docs and (filters["filter_category"] or filters["filter_tags"]):
        logger.info("Filtered searches returned 0 docs. Falling back to global search.")
        retrieved_docs = execute_vector_search(
            query_embedding=query_embedding,
            filter_category=None,
            filter_tags=None,
            match_count=top_k
        )
        
    # 4. Formulate output context String
    context_str = _format_context(retrieved_docs)
    return retrieved_docs, context_str

def _format_context(documents: List[Dict[str, Any]]) -> str:
    """Formats retrieved blocks into reader-friendly markdown contexts for GPT/Llama."""
    if not documents:
        return "No corresponding medical literature was retrieved from the database."

    sections = []
    for i, doc in enumerate(documents, 1):
        source = doc.get("source", "Medical Database")
        cred = doc.get("credibility_score", 0.85)
        sim = doc.get("similarity", 0.0)
        category = doc.get("category", "General")
        tags = ", ".join(doc.get("tags", []))
        
        sections.append(
            f"### Document {i} (Source: {source})\n"
            f"- **Focus**: {doc['topic']} ({doc['subtopic']})\n"
            f"- **Meta**: Category: {category} | Tags: [{tags}]\n"
            f"- **Scientific Credibility**: {cred:.0%} | **Semantic Score**: {sim:.0%}\n\n"
            f"{doc['content']}"
        )
    return "\n\n---\n\n".join(sections)
