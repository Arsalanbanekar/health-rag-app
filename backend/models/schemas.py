"""
Pydantic schemas for request/response validation.
"""
from typing import List, Optional
from pydantic import BaseModel, Field


class HistoryMessage(BaseModel):
    role: str
    content: str

class QueryRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=5000, description="User's health question")
    session_id: Optional[str] = Field(default="anonymous", description="Session ID for logging")
    language: Optional[str] = Field(default="English", description="Response language preference")
    history: Optional[List[HistoryMessage]] = Field(default=[], description="Previous messages in the conversation")


class Source(BaseModel):
    topic: str
    subtopic: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    source_type: Optional[str] = None
    source: Optional[str] = None
    credibility_score: Optional[float] = None
    similarity: Optional[float] = None


class QueryResponse(BaseModel):
    success: bool
    query: str
    response: str
    in_domain: bool
    sources: List[Source] = []
    message: Optional[str] = None


class DocumentInsert(BaseModel):
    topic: str
    subtopic: str
    content: str
    category: str
    tags: List[str] = []
    source_type: str
    source: Optional[str] = None
    credibility_score: float = Field(default=0.85, ge=0.0, le=1.0)
    evidence_level: Optional[str] = None
    embedding: List[float]


class HealthStatus(BaseModel):
    status: str
    knowledge_base_docs: int
    model: str
    embedding_model: str
    vector_db: str
