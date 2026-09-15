# MedAI — Health RAG Assistant

A full-stack RAG (Retrieval-Augmented Generation) health assistant. Answers are grounded in real government health fact sheets, not model memory alone — every response cites the specific source it was retrieved from.

**Stack:** FastAPI + React + Supabase (pgvector) + Groq LLM

## How it works

```
User query
   │
   ▼
Query Classifier ──► Topic / Category detection (regex-based intent matching)
   │
   ▼
Metadata Filter ───► Maps topic → controlled tag vocabulary
   │
   ▼
Embed Query ───────► BAAI/bge-small-en-v1.5 (384-dim, asymmetric retrieval)
   │
   ▼
Hybrid Search ─────► pgvector cosine similarity + category/tag filters (Postgres)
   │                  Cascading fallback: filtered → relaxed → global search
   ▼
Groq LLM ──────────► openai/gpt-oss-120b generates a grounded, cited answer
   │
   ▼
Streamed response + source citations
```

Retrieval isn't pure vector search — it's **hybrid**: a lightweight classifier detects the query's health topic and category first, narrows the candidate set with a Postgres array-overlap filter on metadata tags, then ranks what's left by semantic similarity. If a filtered search comes up empty, it cascades to a looser filter and finally to unfiltered global search, so a query never dead-ends on zero results.

## Knowledge base

The knowledge base is built from real fact sheets published by **MedlinePlus** (U.S. National Library of Medicine / NIH) — not hand-written text. A custom ingestion pipeline (`backend/services/ingestion/`) does the work:

1. **Fetch** — downloads each source page (cached locally so re-runs don't hit the network)
2. **Parse** — template-aware HTML extraction. MedlinePlus serves two distinct page structures (a "topic summary" hub template and a "genetics/condition" template); the parser is scoped to each one specifically so it never ingests the page's link-directory navigation as if it were medical content
3. **Chunk** — sentence-safe splitting at **512 tokens with 50-token overlap**, counted with the embedding model's own tokenizer (not word count) so nothing is silently cut mid-sentence. Overlap carries whole trailing sentences across chunk boundaries so a fact never gets orphaned by a split
4. **Tag** — each chunk is matched against a controlled vocabulary that mirrors the retrieval filters exactly, so every chunk stays reachable by filtered search (a free-form/LLM-extracted tag would silently fall outside the filter and degrade retrieval with no visible error)
5. **Embed & store** — `BAAI/bge-small-en-v1.5` (384-dim, 512-token context) embeddings, written to Supabase in batches

Current corpus: **57 chunks across 10 health topics** (Hair Health, Weight Loss, Muscle Building, Nutrition, Skin Health, Cardiovascular Health, Digestive Health, Sleep, Hormones, General Wellness), each tagged with topic/category/tags/source_type/credibility_score and traceable to its source URL.

Re-seed the database from source URLs:
```bash
cd backend
python scripts/seed_database.py --dry-run   # chunk + validate, no writes
python scripts/seed_database.py             # embed + write to Supabase
```
Sources are declared in `backend/data/sources/manifest.json` (see `manifest.example.json` for the format).

## Features

- **Hybrid retrieval** — metadata filtering + pgvector semantic search with graceful fallback
- **Streaming responses** — token-by-token LLM output over SSE
- **Cited sources** — every answer lists which documents it drew from, with similarity and credibility scores
- **Out-of-domain detection** — non-health questions are caught and redirected before hitting the LLM
- **User accounts & chat history** — Supabase Auth + persisted sessions/messages, so conversations survive a refresh
- **Offline fallback** — if Supabase is unreachable, the backend falls back to a local JSON snapshot of the same corpus rather than failing outright

## Project structure

```
backend/
  main.py                    FastAPI app, routes, streaming endpoint
  services/
    rag_pipeline.py          Orchestrates the full query → response flow
    retrieval/                Hybrid search: classifier, metadata filter, vector search
    ingestion/                 Fetch → parse → chunk → tag pipeline for building the KB
    embeddings.py             bge-small-en-v1.5 wrapper (query vs. passage embedding)
    groq_client.py            LLM generation (streaming + non-streaming)
    supabase_client.py        DB access + offline fallback
  scripts/
    seed_database.py         Ingests sources, embeds, writes to Supabase
    export_docs.py            Refreshes the offline fallback JSON
  data/sources/manifest.json Source URLs + metadata (not committed — see .example)
  supabase_schema.sql         medical_documents table + match_medical_documents() RPC
  supabase_chat_schema.sql    chat_sessions / chat_messages tables

frontend/
  src/App.jsx                Chat UI, auth state, streaming message rendering
  src/Auth.jsx                Sign-in/sign-up
  src/components/            Settings, loading skeletons
```

## Running locally

**Backend**
```bash
cd backend
pip install -r requirements.txt
cp .env.example .env   # fill in GROQ_API_KEY, SUPABASE_URL, SUPABASE_ANON_KEY
uvicorn main:app --reload --port 8000
```

**Frontend**
```bash
cd frontend
npm install
npm run dev             # http://localhost:5173
```

**Database** — run `backend/supabase_schema.sql` and `backend/supabase_chat_schema.sql` in the Supabase SQL Editor, then seed:
```bash
python backend/scripts/seed_database.py
```

## Evaluation

`run_eval_groq.py` scores end-to-end response quality using an LLM judge (Groq, OpenAI, or Claude), tracking correctness and groundedness against the retrieved sources. Results land in `eval_results.csv`.

## Deployment

`render.yaml` deploys the backend on Render. The frontend is a static Vite build, deployable to any static host (Vercel, Netlify, etc.) pointed at the deployed backend URL via `VITE_API_URL`.
