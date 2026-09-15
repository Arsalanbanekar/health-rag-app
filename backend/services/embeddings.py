"""
Embeddings Service
Uses fastembed (ONNX Runtime) for local, private, low-memory vector generation.
Generates 384-dimensional vectors using BAAI/bge-small-en-v1.5.

Why fastembed over sentence-transformers: identical model, identical 384-dim
output, but no PyTorch. Measured directly: importing sentence-transformers
pulled in torch, which alone cost ~400MB of resident memory before any model
was even loaded, and the full embed pipeline peaked at ~504MB — enough by
itself to OOM-kill the backend on a 512MB host (confirmed: that is exactly
what happened on Render's free tier). fastembed uses onnxruntime directly;
the same measurement methodology puts the full pipeline at ~190MB, with
output verified numerically near-identical to the previous implementation
(cosine similarity > 0.9999988 on the same input).

fastembed's own query_embed()/passage_embed() split does NOT apply bge's
asymmetric query-instruction prefix for this model — verified empirically:
query_embed() and passage_embed() return identical output for the same text.
The prefix is therefore still applied manually below, exactly as before.
Skipping it is a real, measured regression: an unprefixed query embedding
compared against the correctly-prefixed one for the same query scores only
~0.97 cosine similarity — a visible drop in retrieval relevance, not noise.
Do not replace embed_query()'s manual prefix with model.query_embed()
without re-verifying this for whatever model is in use at the time.
"""
import logging
from typing import List

try:
    from fastembed import TextEmbedding
except ImportError:
    TextEmbedding = None

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
# so usable content is 2 tokens less than the raw ceiling. fastembed's own
# token_count() includes these two special tokens (verified: the offset is
# exactly 2 regardless of text length) — count_tokens() below subtracts them
# so its contract (content tokens only) matches the original implementation.
SPECIAL_TOKEN_RESERVE = 2
MAX_CONTENT_TOKENS = MAX_SEQ_TOKENS - SPECIAL_TOKEN_RESERVE

# Prefix bge-v1.5 expects on the query side of a retrieval pair.
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


class EmbeddingTooLongError(ValueError):
    """Raised when text would be silently truncated by the model."""


class EmbeddingService:
    _instance = None
    _model = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(EmbeddingService, cls).__new__(cls)
        return cls._instance

    def load_model(self):
        """Lazy load the fastembed model to save memory until needed."""
        if self._model is None:
            if TextEmbedding is None:
                raise ImportError("fastembed is not installed.")
            logger.info(f"Loading fastembed {MODEL_NAME} model...")
            self._model = TextEmbedding(MODEL_NAME)
            logger.info("Model loaded successfully.")
        return self._model

    def count_tokens(self, text: str) -> int:
        """Count content tokens exactly as the embedding model would."""
        model = self.load_model()
        return model.token_count(text) - SPECIAL_TOKEN_RESERVE

    def _assert_within_limit(self, texts: List[str]) -> None:
        """
        Fail loudly on over-length input.

        fastembed truncates past the model's max sequence length without
        warning (same as sentence-transformers did), so an over-long chunk
        would lose its tail with no error anywhere in the logs. That is data
        loss disguised as success — refuse it instead.
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
        return [vec.tolist() for vec in model.embed(texts, batch_size=batch_size)]

    def embed_query(self, query: str) -> List[float]:
        """
        Embed a user query for retrieval, with the instruction prefix bge
        expects, applied manually (see module docstring — fastembed's own
        query_embed() does not apply it for this model).

        Queries are short, so over-length input is truncated here rather than
        raised — a search should degrade, not fail.
        """
        model = self.load_model()
        vec = list(model.embed([QUERY_INSTRUCTION + query]))[0]
        return vec.tolist()


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
