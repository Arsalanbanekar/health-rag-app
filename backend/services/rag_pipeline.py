"""
RAG Pipeline — Hybrid Retrieval (Metadata + Vector) + LLM generation.
"""
import logging
import re
from typing import List, Dict, Tuple

from services.supabase_client import log_query, log_out_of_domain
from services.groq_client import generate_response, stream_response
from services.retrieval.hybrid_search import perform_hybrid_retrieval

logger = logging.getLogger(__name__)

# Non-health questions are filtered at the gate
NON_HEALTH_SIGNALS = [
    r"^\s*what is \d+[\s\+\-\*\/]\d+",          # math expressions
    r"^\s*write (me )?(a |an )?(poem|story|essay|song|code|script|program)",
    r"^\s*(translate|convert) .+ (to|into) ",
    r"^\s*who (wrote|directed|created|invented) ",
    r"^\s*(what|who) (is|are) (the )?(capital|president|prime minister|ceo|founder) of ",
    r"^\s*what (year|day|date) (was|did|is) ",
]


def is_non_health_query(query: str) -> bool:
    """
    Returns True if the query is identified as out-of-domain (non-health related).
    """
    q = query.strip().lower()
    for pattern in NON_HEALTH_SIGNALS:
        if re.search(pattern, q, re.IGNORECASE):
            return True
    return False


def retrieve_context(query: str) -> Tuple[List[Dict], str]:
    """
    Retrieves contexts from the database using our new Hybrid Search package.
    Kept for backwards compatibility with test files or direct imports.
    """
    try:
        return perform_hybrid_retrieval(query)
    except Exception as e:
        logger.error(f"Hybrid retrieval failed, returning empty context: {e}")
        return [], ""


def process_query(
    query: str,
    session_id: str = "anonymous",
    conversation_history: List[Dict] = None,
) -> dict:
    """
    Full Hybrid RAG pipeline:
    1. Soft domain validation check.
    2. Intent Classification + Metadata Extraction.
    3. Dense Vector Similarity Search with Metadata filters.
    4. LLM Generation via Groq API.
    5. Logging query details for system intelligence.
    """
    # Step 1: Filter out-of-domain queries
    if is_non_health_query(query):
        out_of_domain_msg = (
            "I'm MedAI, your personal health and medical assistant. "
            "I can help with any health or medical topic — from symptoms and medications "
            "to nutrition, fitness, mental health, chronic diseases, and more.\n\n"
            "Please ask me a health-related question and I'll provide evidence-based guidance! 🩺"
        )
        log_out_of_domain(query, session_id)
        log_query(query, out_of_domain_msg, False, [], session_id)
        return {
            "success": False,
            "query": query,
            "response": out_of_domain_msg,
            "in_domain": False,
            "sources": [],
            "message": "out_of_domain",
        }

    # Step 2 & 3: Run intent-based hybrid metadata-vector search
    retrieved_docs, context = retrieve_context(query)

    # Step 4: Perform reasoning/inference via Groq client
    try:
        llm_response = generate_response(query, context, conversation_history=conversation_history)
    except Exception as e:
        logger.error(f"LLM generation failed: {e}")
        return {
            "success": False,
            "query": query,
            "response": "⚠️ Our AI is temporarily unavailable. Please try again in a moment.",
            "in_domain": True,
            "sources": [],
            "message": "llm_error",
        }

    # Step 5: Collect metadata-rich sources for UI presentation
    sources = [
        {
            "topic": doc.get("topic", ""),
            "subtopic": doc.get("subtopic", ""),
            "category": doc.get("category", ""),
            "tags": doc.get("tags", []),
            "source_type": doc.get("source_type", ""),
            "source": doc.get("source", "Medical Database"),
            "credibility_score": doc.get("credibility_score", 0),
            "similarity": doc.get("similarity", 0),
        }
        for doc in retrieved_docs
    ]

    # Log to training outputs
    log_query(query, llm_response, True, sources, session_id)

    return {
        "success": True,
        "query": query,
        "response": llm_response,
        "in_domain": True,
        "sources": sources,
        "message": "ok",
    }
