"""
MedAI — Health & Wellness RAG Assistant — FastAPI Backend
Powered by: Groq (LLM) + Keyword Retrieval (vectorless) + Supabase (storage)
Upgraded: Removed domain restriction, removed vector search, full multi-domain health AI.
"""
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import json
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from models.schemas import QueryRequest, QueryResponse, HealthStatus
from services.rag_pipeline import process_query, retrieve_context, format_retrieved_context
from services.supabase_client import get_documents_count, log_query, get_supabase
from services.groq_client import stream_response

load_dotenv()

# Logging setup
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/app.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# Track metrics in memory
metrics = {
    "total_queries": 0,
    "successful": 0,
    "failed": 0,
    "out_of_domain": 0,
    "start_time": time.time(),
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Startup — no embedding model needed in vectorless mode."""
    logger.info("🚀 Starting MedAI Health RAG API (vectorless mode)...")
    logger.info("✅ Server ready — accepting requests.")
    yield
    logger.info("🛑 Shutting down MedAI Health RAG API...")


app = FastAPI(
    title="MedAI — Health & Wellness RAG API",
    description="Elite multi-domain health AI powered by Groq LLM + keyword retrieval",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS — local dev + production frontend only
DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
    "https://your-app.vercel.app",
]
_cors_env = os.getenv("CORS_ORIGINS")
cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()] if _cors_env else DEFAULT_CORS_ORIGINS
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────
# LATENCY LOGGING MIDDLEWARE
# ──────────────────────────────────────────────
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class LatencyLoggingMiddleware(BaseHTTPMiddleware):
    """Logs method, path, status code, and response time (ms) for every request."""

    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        duration_ms = round((time.time() - start) * 1000, 1)
        logger.info(
            f"⏱  {request.method} {request.url.path} → {response.status_code} in {duration_ms}ms"
        )
        return response


app.add_middleware(LatencyLoggingMiddleware)


# ──────────────────────────────────────────────
# ROUTES
# ──────────────────────────────────────────────


@app.get("/health", response_model=HealthStatus)
async def health_check():
    """System health check."""
    doc_count = get_documents_count()
    return HealthStatus(
        status="ok",
        knowledge_base_docs=doc_count,
        model="llama-3.3-70b-versatile (Groq)",
        embedding_model="keyword-retrieval (vectorless)",
        vector_db="Supabase (keyword ranked)",
    )


@app.get("/metrics")
async def get_metrics():
    """Real-time metrics for monitoring."""
    uptime = time.time() - metrics["start_time"]
    return {
        **metrics,
        "uptime_seconds": round(uptime),
        "uptime_human": f"{int(uptime // 3600)}h {int((uptime % 3600) // 60)}m",
    }


@app.post("/query", response_model=QueryResponse)
async def query_health(request: QueryRequest):
    """
    Main RAG endpoint. Accepts any health question and returns an
    evidence-based answer with sources and medical disclaimer.
    """
    metrics["total_queries"] += 1
    logger.info(f"📝 Query: {request.query[:100]}...")

    try:
        result = process_query(request.query, request.session_id)

        if result["in_domain"]:
            metrics["successful"] += 1
        else:
            metrics["out_of_domain"] += 1

        return QueryResponse(**result)

    except Exception as e:
        metrics["failed"] += 1
        logger.error(f"Query processing failed: {e}")
        return QueryResponse(
            success=False,
            query=request.query,
            response="⚠️ Something went wrong. Please try again.",
            in_domain=True,
            sources=[],
            message="server_error",
        )


@app.post("/query/stream")
async def query_health_stream(request: QueryRequest):
    """
    Streaming version of the query endpoint.
    Returns a text/event-stream for real-time token display in the UI.
    No domain restriction — all health questions are answered.
    """
    metrics["total_queries"] += 1
    logger.info(f"🔄 Stream query: {request.query[:80]}...")

    # Parse conversation history from request
    conversation_history = [{"role": msg.role, "content": msg.content} for msg in request.history] if request.history else []

    # Keyword-based retrieval (vectorless)
    try:
        retrieved_docs, context = retrieve_context(request.query)
    except Exception as e:
        logger.error(f"Retrieval error: {e}")
        retrieved_docs, context = [], ""

    # Stream from Groq
    async def token_stream():
        full_response = []
        try:
            for token in stream_response(request.query, context, conversation_history, language=request.language):
                full_response.append(token)
                yield f"data: {json.dumps(token)}\n\n"
            yield "data: [DONE]\n\n"

            # Log after full response is done
            metrics["successful"] += 1
            sources = [
                {
                    "topic": d.get("topic", ""),
                    "subtopic": d.get("subtopic", ""),
                    "source": d.get("source", ""),
                    "credibility_score": d.get("credibility_score", 0),
                    "similarity": d.get("similarity", 0),
                }
                for d in retrieved_docs
            ]
            log_query(request.query, "".join(full_response), True, sources, request.session_id)

        except Exception as e:
            logger.error(f"Stream error: {e}")
            metrics["failed"] += 1
            yield f"data: {json.dumps('⚠️ Error: ' + str(e))}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(token_stream(), media_type="text/event-stream")


@app.get("/domains")
async def get_domains():
    """Return all supported health domains (for UI topic cards)."""
    return {
        "domains": [
            {"id": "hair", "name": "Hair Health", "icon": "💇", "description": "Hair loss, growth, treatments, nutrition"},
            {"id": "weight", "name": "Weight Management", "icon": "⚖️", "description": "Weight loss, gain, metabolism, meal plans"},
            {"id": "muscle", "name": "Muscle Building", "icon": "💪", "description": "Training, protein, recovery, supplements"},
            {"id": "hormones", "name": "Hormones", "icon": "🧬", "description": "Testosterone, thyroid, cortisol, balance"},
            {"id": "nutrition", "name": "Nutrition", "icon": "🥗", "description": "Vitamins, diet, supplements, deficiencies"},
            {"id": "fitness", "name": "Fitness", "icon": "🏃", "description": "Cardio, strength, flexibility, endurance"},
            {"id": "sleep", "name": "Sleep & Stress", "icon": "😴", "description": "Sleep quality, stress reduction, mental health"},
            {"id": "general", "name": "General Health", "icon": "❤️", "description": "Heart, gut, skin, immunity, longevity"},
        ]
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
