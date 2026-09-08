"""
Embeddings Service
Uses HuggingFace sentence-transformers for local, private vector generation.
Generates 384-dimensional vectors using BAAI/bge-small-en-v1.5.

Why bge-small-en-v1.5 over all-MiniLM-L6-v2: identical 384-dim output (so the
Postgres `vector(384)` column and match_medical_documents() are unchanged), but
a 512-token context instead of 256. MiniLM silently truncated anything past 256
tokens, which meant the tail of every long document was never embedded at all.

bge is an *asymmetric* retrieval model: queries get an instruction prefix,
passages do not. Use embed_query() for user queries and embed_passages() for
documents being indexed — mixing them up measurably degrades recall.
"""
import logging
from typing import List

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None

try:
    from transformers import AutoTokenizer
except ImportError:
    AutoTokenizer = None

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────
# MODEL CONFIGURATION
# Single source of truth — the chunker imports these so chunk
# budgets can never drift away from what the model accepts.
# ────────────────────────────────────────────────────────────
MODEL_NAME = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384

# Hard ceiling enforced by the model's position embeddings.
MAX_SEQ_TOKENS = 512

# [CLS] and [SEP] are added at encode time and count against MAX_SEQ_TOKENS,
# so usable content is 2 tokens less than the raw ceiling.
SPECIAL_TOKEN_RESERVE = 2
MAX_CONTENT_TOKENS = MAX_SEQ_TOKENS - SPECIAL_TOKEN_RESERVE

# Prefix bge-v1.5 expects on the query side of a retrieval pair.
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


class EmbeddingTooLongError(ValueError):
    """Raised when text would be silently truncated by the model."""


class EmbeddingService:
    _instance = None
    _model = None
    _tokenizer = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(EmbeddingService, cls).__new__(cls)
        return cls._instance

    def load_model(self):
        """Lazy load the sentence transformer model to save memory until needed."""
        if self._model is None:
            if SentenceTransformer is None:
                raise ImportError("sentence-transformers is not installed.")
            logger.info(f"Loading HuggingFace {MODEL_NAME} model...")
            self._model = SentenceTransformer(MODEL_NAME)
            self._model.max_seq_length = MAX_SEQ_TOKENS
            logger.info("Model loaded successfully.")
        return self._model

    def load_tokenizer(self):
        """
        Load just the tokenizer. Much cheaper than the full model — the chunker
        needs token counts but not vectors.
        """
        if self._tokenizer is None:
            if AutoTokenizer is None:
                raise ImportError("transformers is not installed.")
            self._tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        return self._tokenizer

    def count_tokens(self, text: str) -> int:
        """Count content tokens exactly as the embedding model would."""
        tokenizer = self.load_tokenizer()
        return len(tokenizer.encode(text, add_special_tokens=False))

    def _assert_within_limit(self, texts: List[str]) -> None:
        """
        Fail loudly on over-length input.

        sentence-transformers truncates past max_seq_length without warning, so
        an over-long chunk loses its tail with no error anywhere in the logs.
        That is data loss disguised as success — refuse it instead.
        """
        offenders = []
        for i, text in enumerate(texts):
            n = self.count_tokens(text)
            if n > MAX_CONTENT_TOKENS:
                offenders.append((i, n, text[:80]))

        if offenders:
            detail = "\n".join(
                f"  [{i}] {n} tokens (limit {MAX_CONTENT_TOKENS}): {preview!r}..."
                for i, n, preview in offenders
            )
            raise EmbeddingTooLongError(
                f"{len(offenders)} text(s) exceed the model's {MAX_CONTENT_TOKENS}-token "
                f"content limit and would be silently truncated:\n{detail}"
            )

    def embed_passages(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        """
        Embed documents for indexing. No instruction prefix (bge convention).
        Raises EmbeddingTooLongError rather than truncating.
        """
        if not texts:
            return []
        self._assert_within_limit(texts)
        model = self.load_model()
        return model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        ).tolist()

    def embed_query(self, query: str) -> List[float]:
        """
        Embed a user query for retrieval, with the instruction prefix bge expects.

        Queries are short, so over-length input is truncated here rather than
        raised — a search should degrade, not fail.
        """
        model = self.load_model()
        return model.encode(
            QUERY_INSTRUCTION + query,
            normalize_embeddings=True,
            show_progress_bar=False,
        ).tolist()


# Global access functions for convenience
_service = EmbeddingService()


def load_model():
    return _service.load_model()


def count_tokens(text: str) -> int:
    return _service.count_tokens(text)


def embed_query(query: str) -> List[float]:
    return _service.embed_query(query)


def embed_passages(texts: List[str], batch_size: int = 32) -> List[List[float]]:
    return _service.embed_passages(texts, batch_size=batch_size)


def embed_text(text: str) -> List[float]:
    """Backwards-compatible alias. Callers of this are on the query path."""
    return _service.embed_query(text)


def embed_batch(texts: List[str]) -> List[List[float]]:
    """Backwards-compatible alias for the indexing path."""
    return _service.embed_passages(texts)
