"""
RAG Pipeline — Vectorless keyword-based retrieval + LLM generation.
Upgraded: removed domain restriction, removed vector search, added keyword retrieval fallback.
"""
import logging
import re
from typing import List, Dict

from services.embeddings import rank_documents_by_keyword
from services.supabase_client import get_all_documents, log_query, log_out_of_domain
from services.groq_client import generate_response, stream_response

logger = logging.getLogger(__name__)

# Only truly non-health questions are rejected — math, poetry, coding, etc.
# We use a small blocklist of pure off-topic signals instead of a narrow allowlist.
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
    Returns True only if the query is CLEARLY not health-related at all.
    We use a small blocklist instead of a narrow allowlist — everything else is passed to the LLM.
    """
    q = query.strip().lower()
    for pattern in NON_HEALTH_SIGNALS:
        if re.search(pattern, q, re.IGNORECASE):
            return True
    return False


def format_retrieved_context(documents: List[dict]) -> str:
    """Format retrieved medical documents into a readable context block for the LLM."""
    if not documents:
        return ""

    sections = []
    for i, doc in enumerate(documents, 1):
        source_info = f" (Source: {doc.get('source', 'Medical Database')})" if doc.get("source") else ""
        credibility = doc.get("credibility_score", 0)
        similarity = doc.get("similarity", 0)
        sections.append(
            f"### Document {i}{source_info}\n"
            f"**Topic**: {doc.get('topic', 'N/A')} — {doc.get('subtopic', '')}\n"
            f"**Credibility**: {credibility:.0%} | **Relevance**: {similarity:.0%}\n\n"
            f"{doc.get('content', '')}"
        )
    return "\n\n---\n\n".join(sections)


def retrieve_context(query: str) -> tuple[List[dict], str]:
    """
    Vectorless retrieval: fetch all docs from Supabase, rank by keyword match.
    Returns (retrieved_docs, formatted_context_string).
    """
    try:
        all_docs = get_all_documents()
        if not all_docs:
            return [], ""
        ranked = rank_documents_by_keyword(query, all_docs, top_k=6, threshold=0.05)
        context = format_retrieved_context(ranked)
        return ranked, context
    except Exception as e:
        logger.warning(f"Keyword retrieval failed, falling back to no context: {e}")
        return [], ""


def process_query(
    query: str,
    session_id: str = "anonymous",
    conversation_history: List[Dict] = None,
) -> dict:
    """
    Full RAG pipeline (vectorless):
    1. Soft non-health check (only block clearly off-topic queries)
    2. Keyword-based document retrieval from Supabase
    3. LLM generation with context + conversation history
    4. Log everything
    """
    # Step 1: Only block truly non-health queries
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

    # Step 2: Keyword-based document retrieval (vectorless)
    retrieved_docs, context = retrieve_context(query)

    # Step 3: LLM generation with context and conversation history
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

    # Step 4: Collect sources
    sources = [
        {
            "topic": doc.get("topic", ""),
            "subtopic": doc.get("subtopic", ""),
            "source": doc.get("source", "Medical Database"),
            "credibility_score": doc.get("credibility_score", 0),
            "similarity": doc.get("similarity", 0),
        }
        for doc in retrieved_docs
    ]

    # Step 5: Log for training
    log_query(query, llm_response, True, sources, session_id)

    return {
        "success": True,
        "query": query,
        "response": llm_response,
        "in_domain": True,
        "sources": sources,
        "message": "ok",
    }
