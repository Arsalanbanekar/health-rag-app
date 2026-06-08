-- ============================================================
-- SUPABASE SCHEMA — Run this in Supabase SQL Editor
-- (Dashboard → SQL Editor → New query → Paste & Run)
-- ============================================================

-- 1. Enable pgvector extension (open source)
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Medical Knowledge Base (your RAG data)
CREATE TABLE IF NOT EXISTS medical_documents (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    topic TEXT NOT NULL,                          -- e.g. "Hair Health"
    subtopic TEXT,                                -- e.g. "Minoxidil Treatment"
    content TEXT NOT NULL,                        -- Full medical text
    source TEXT,                                  -- e.g. "PubMed #12345"
    credibility_score FLOAT DEFAULT 0.85,         -- 0.0 to 1.0
    evidence_level TEXT,                          -- e.g. "clinical_trial"
    embedding vector(384),                        -- 384-dim for all-MiniLM-L6-v2
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Vector similarity search function
CREATE OR REPLACE FUNCTION match_medical_documents(
    query_embedding vector(384),
    match_threshold FLOAT DEFAULT 0.4,
    match_count INT DEFAULT 10
)
RETURNS TABLE (
    id UUID,
    topic TEXT,
    subtopic TEXT,
    content TEXT,
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
        md.source,
        md.credibility_score,
        md.evidence_level,
        1 - (md.embedding <=> query_embedding) AS similarity
    FROM medical_documents md
    WHERE 1 - (md.embedding <=> query_embedding) > match_threshold
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
CREATE INDEX IF NOT EXISTS idx_query_logs_session ON query_logs (session_id);
CREATE INDEX IF NOT EXISTS idx_query_logs_domain ON query_logs (in_domain);
CREATE INDEX IF NOT EXISTS idx_ood_created ON out_of_domain_queries (created_at);

-- 7. IVFFlat index on embeddings for fast vector search
-- NOTE: Run this AFTER you have inserted at least 100 documents.
-- Until then, pgvector will use sequential scan (still works fine).
-- CREATE INDEX ON medical_documents USING ivfflat (embedding vector_cosine_ops) WITH (lists = 20);

-- ============================================================
-- HELPFUL QUERIES (run these anytime to see your training data)
-- ============================================================

-- See out-of-domain patterns (what topics to expand):
-- SELECT query, COUNT(*) AS freq FROM out_of_domain_queries
-- GROUP BY query ORDER BY freq DESC LIMIT 20;

-- See total queries:
-- SELECT in_domain, COUNT(*) FROM query_logs GROUP BY in_domain;

-- See knowledge base size:
-- SELECT topic, COUNT(*) FROM medical_documents GROUP BY topic;
