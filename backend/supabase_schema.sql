-- ============================================================
-- SUPABASE SCHEMA — Run this in Supabase SQL Editor
-- (Dashboard → SQL Editor → New query → Paste & Run)
-- Hybrid RAG Architecture (Metadata + pgvector)
-- ============================================================

-- 1. Enable pgvector extension (open source)
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Medical Knowledge Base (Hybrid RAG)
CREATE TABLE IF NOT EXISTS medical_documents (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    
    -- Text/Content
    topic TEXT NOT NULL,                          -- e.g. "Hair Health"
    subtopic TEXT NOT NULL,                       -- e.g. "Causes of Hair Loss"
    content TEXT NOT NULL,                        -- Full medical text
    
    -- Metadata (for filtering)
    category TEXT NOT NULL,                       -- e.g. "Diagnosis", "Treatment"
    tags TEXT[] NOT NULL DEFAULT '{}',            -- Detailed keyword tags array
    source_type TEXT NOT NULL,                    -- e.g. "clinical_guideline", "government_health_portal"
                                                   -- (see services/ingestion/taxonomy.py for the full set)
    
    -- Verification/Scoring
    source TEXT,                                  -- Source URL or name
    credibility_score FLOAT DEFAULT 0.85,         -- 0.0 to 1.0 scale
    evidence_level TEXT,                          -- Evidence level classification
    updated_at TIMESTAMPTZ DEFAULT NOW(),         -- For freshness
    
    -- Encodings
    embedding vector(384),                        -- 384-dim for all-MiniLM-L6-v2
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Hybrid Vector Similarity Search Function
-- Accepts an embedding for semantic search and optional metadata filters.
CREATE OR REPLACE FUNCTION match_medical_documents(
    query_embedding vector(384),
    filter_category TEXT DEFAULT NULL,
    filter_tags TEXT[] DEFAULT NULL,
    match_threshold FLOAT DEFAULT 0.4,
    match_count INT DEFAULT 10
)
RETURNS TABLE (
    id UUID,
    topic TEXT,
    subtopic TEXT,
    content TEXT,
    category TEXT,
    tags TEXT[],
    source_type TEXT,
    source TEXT,
    credibility_score FLOAT,
    evidence_level TEXT,
    similarity FLOAT
)
LANGUAGE sql STABLE
AS $$
    SELECT
        md.id,
        md.topic,
        md.subtopic,
        md.content,
        md.category,
        md.tags,
        md.source_type,
        md.source,
        md.credibility_score,
        md.evidence_level,
        1 - (md.embedding <=> query_embedding) AS similarity
    FROM medical_documents md
    WHERE 
        (1 - (md.embedding <=> query_embedding) > match_threshold)
        -- Apply Category Filter if provided
        AND (filter_category IS NULL OR md.category = filter_category)
        -- Apply Tags Filter if provided (checks if arrays overlap / share any elements)
        AND (filter_tags IS NULL OR md.tags && filter_tags)
    ORDER BY similarity DESC
    LIMIT match_count;
$$;

-- 4. Query logs (for training data)
CREATE TABLE IF NOT EXISTS query_logs (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL DEFAULT 'anonymous',
    query TEXT NOT NULL,
    response TEXT NOT NULL,
    in_domain BOOLEAN DEFAULT TRUE,
    sources JSONB DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 5. Out-of-domain queries (for training expansion)
CREATE TABLE IF NOT EXISTS out_of_domain_queries (
    id BIGSERIAL PRIMARY KEY,
    query TEXT NOT NULL,
    session_id TEXT DEFAULT 'anonymous',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 6. Indexes for performance
CREATE INDEX IF NOT EXISTS idx_medical_docs_topic ON medical_documents (topic);
CREATE INDEX IF NOT EXISTS idx_medical_docs_category ON medical_documents (category);
CREATE INDEX IF NOT EXISTS idx_medical_docs_tags ON medical_documents USING GIN (tags);

CREATE INDEX IF NOT EXISTS idx_query_logs_session ON query_logs (session_id);
CREATE INDEX IF NOT EXISTS idx_query_logs_domain ON query_logs (in_domain);
CREATE INDEX IF NOT EXISTS idx_ood_created ON out_of_domain_queries (created_at);

-- 7. IVFFlat index on embeddings for fast vector search
-- NOTE: Run this AFTER you have inserted at least 100 documents.
-- CREATE INDEX ON medical_documents USING ivfflat (embedding vector_cosine_ops) WITH (lists = 20);
