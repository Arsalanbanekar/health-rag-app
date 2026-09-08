"""
Chunking Module
Splits source documents into overlapping, embedding-sized passages.

Design notes:
  * Token counts come from the *embedding model's own tokenizer*, not a word
    count and not tiktoken. tiktoken is OpenAI BPE; bge uses BERT WordPiece and
    the two disagree by 20-40% on medical vocabulary ("dihydrotestosterone" is
    one tiktoken-ish unit but many WordPiece pieces). Counting with the wrong
    tokenizer means chunks that overflow and get truncated.
  * Splits respect structure: section -> paragraph -> sentence. A chunk never
    starts or ends mid-sentence, because a severed clause embeds poorly and
    reads badly when handed to the LLM as context.
  * Overlap carries whole trailing sentences, so a fact split across a chunk
    boundary still appears intact in one of the two chunks.
"""
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

from services.embeddings import MAX_CONTENT_TOKENS, MAX_SEQ_TOKENS, count_tokens

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────
# TUNABLES
# ────────────────────────────────────────────────────────────
DEFAULT_CHUNK_TOKENS = 512
DEFAULT_OVERLAP_TOKENS = 50

# Chunks below this are almost always page furniture ("Learn more", "See also",
# a stray caption). Merged into a neighbour when possible, dropped otherwise.
MIN_CHUNK_TOKENS = 40

# Abbreviations that end in a period but do not end a sentence. Without these
# the splitter breaks "500 mg. daily" and "vitamin D vs. placebo" mid-sentence.
_ABBREVIATIONS = [
    "approx", "cal", "dr", "e.g", "et al", "etc", "fig", "g", "i.e", "inc",
    "kg", "max", "mcg", "mg", "min", "ml", "mmhg", "mr", "mrs", "ms", "no",
    "oz", "ph", "prof", "st", "vs", "yr",
]
_ABBREV_PATTERN = "|".join(re.escape(a) for a in _ABBREVIATIONS)

# Python's re only supports fixed-width lookbehind, so variable-length
# abbreviations cannot be excluded with a negative lookbehind. Instead, mask the
# periods that do not end a sentence, split, then unmask.
_PERIOD_SENTINEL = "\x00"

_PROTECT_PATTERNS = [
    # Known abbreviations: "500 mg. daily", "vitamin D vs. placebo"
    re.compile(r"\b(" + _ABBREV_PATTERN + r")\.", re.IGNORECASE),
    # Single-letter initials: "J. Smith"
    re.compile(r"\b([A-Z])\."),
    # Decimals: "1.5", "0.025"
    re.compile(r"(\d)\.(?=\d)"),
]

# Split after . ! ? followed by whitespace and a capital letter or digit.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])[\"')\]]*\s+(?=[A-Z0-9])")

_WHITESPACE = re.compile(r"\s+")


@dataclass
class Section:
    """A heading plus the paragraphs beneath it, as parsed from a source page."""
    heading: str
    paragraphs: List[str] = field(default_factory=list)


@dataclass
class Chunk:
    """One embedding-sized passage, ready for metadata enrichment."""
    text: str
    heading: str
    section_index: int
    chunk_index: int
    token_count: int


def normalize_whitespace(text: str) -> str:
    """Collapse runs of whitespace; source HTML is full of newlines and tabs."""
    return _WHITESPACE.sub(" ", text).strip()


def split_sentences(text: str) -> List[str]:
    """Split a paragraph into sentences, tolerating medical abbreviations."""
    text = normalize_whitespace(text)
    if not text:
        return []

    masked = text
    for pattern in _PROTECT_PATTERNS:
        masked = pattern.sub(r"\1" + _PERIOD_SENTINEL, masked)

    parts = _SENTENCE_BOUNDARY.split(masked)
    return [
        p.replace(_PERIOD_SENTINEL, ".").strip()
        for p in parts
        if p.replace(_PERIOD_SENTINEL, ".").strip()
    ]


def _split_oversized_sentence(sentence: str, budget: int) -> List[str]:
    """
    Last resort for a single sentence longer than the whole token budget.

    Rare (a run-on list of nutrients, a table flattened to prose), but it must
    not crash the pipeline or silently produce an over-length chunk. Splits on
    word boundaries so the pieces stay readable.
    """
    words = sentence.split()
    pieces: List[str] = []
    current: List[str] = []

    for word in words:
        candidate = " ".join(current + [word])
        if current and count_tokens(candidate) > budget:
            pieces.append(" ".join(current))
            current = [word]
        else:
            current.append(word)

    if current:
        pieces.append(" ".join(current))

    logger.warning(
        f"Sentence of {count_tokens(sentence)} tokens exceeded the {budget}-token "
        f"budget; hard-split into {len(pieces)} pieces."
    )
    return pieces


def _overlap_tail(sentences: List[str], overlap_tokens: int) -> List[str]:
    """
    Take whole sentences from the end of a chunk until `overlap_tokens` is met.

    Returns them in original order. Never returns the entire chunk — an overlap
    that swallows its own chunk would loop forever.
    """
    if overlap_tokens <= 0 or len(sentences) <= 1:
        return []

    tail: List[str] = []
    total = 0
    # Walk backwards, stopping one short of consuming every sentence.
    for sentence in reversed(sentences[1:]):
        tail.insert(0, sentence)
        total += count_tokens(sentence)
        if total >= overlap_tokens:
            break
    return tail


def chunk_sections(
    sections: List[Section],
    chunk_tokens: int = DEFAULT_CHUNK_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
    min_tokens: int = MIN_CHUNK_TOKENS,
) -> List[Chunk]:
    """
    Pack structured sections into overlapping chunks.

    Chunks never span sections: a passage about "Symptoms" should not bleed into
    "Treatment", since the two carry different metadata and answer different
    questions.
    """
    # A requested size of 512 means "a full model sequence"; the 2 special
    # tokens come out of it silently. Only warn when the request genuinely
    # exceeds what the model can accept.
    budget = min(chunk_tokens, MAX_CONTENT_TOKENS)
    if chunk_tokens > MAX_SEQ_TOKENS:
        logger.warning(
            f"Requested chunk size {chunk_tokens} exceeds the model's "
            f"{MAX_SEQ_TOKENS}-token ceiling; clamping to {MAX_CONTENT_TOKENS}."
        )
    if overlap_tokens >= budget:
        raise ValueError(
            f"overlap_tokens ({overlap_tokens}) must be smaller than the "
            f"chunk budget ({budget})."
        )

    chunks: List[Chunk] = []

    for section_index, section in enumerate(sections):
        sentences: List[str] = []
        for paragraph in section.paragraphs:
            sentences.extend(split_sentences(paragraph))

        if not sentences:
            continue

        # Break any sentence that cannot fit on its own before packing.
        expanded: List[str] = []
        for sentence in sentences:
            if count_tokens(sentence) > budget:
                expanded.extend(_split_oversized_sentence(sentence, budget))
            else:
                expanded.append(sentence)

        section_chunks = _pack_sentences(expanded, budget, overlap_tokens)

        for text in section_chunks:
            chunks.append(
                Chunk(
                    text=text,
                    heading=section.heading,
                    section_index=section_index,
                    chunk_index=len(chunks),
                    token_count=count_tokens(text),
                )
            )

    return _absorb_undersized(chunks, budget, min_tokens)


def _pack_sentences(
    sentences: List[str],
    budget: int,
    overlap_tokens: int,
) -> List[str]:
    """Greedily fill chunks to `budget`, seeding each with the previous tail."""
    chunks: List[str] = []
    current: List[str] = []
    current_tokens = 0

    for sentence in sentences:
        sentence_tokens = count_tokens(sentence)

        if current and current_tokens + sentence_tokens > budget:
            chunks.append(" ".join(current))
            carry = _overlap_tail(current, overlap_tokens)
            current = carry + [sentence]
            current_tokens = sum(count_tokens(s) for s in current)
        else:
            current.append(sentence)
            current_tokens += sentence_tokens

    if current:
        chunks.append(" ".join(current))

    return chunks


def _absorb_undersized(
    chunks: List[Chunk],
    budget: int,
    min_tokens: int,
) -> List[Chunk]:
    """
    Merge sub-minimum chunks into the previous chunk of the same section, or
    drop them if they stand alone. Keeps stray fragments out of the index.
    """
    if not chunks:
        return []

    kept: List[Chunk] = []
    dropped = 0

    for chunk in chunks:
        if chunk.token_count >= min_tokens:
            kept.append(chunk)
            continue

        previous = kept[-1] if kept else None
        can_merge = (
            previous is not None
            and previous.section_index == chunk.section_index
            and previous.token_count + chunk.token_count <= budget
        )

        if can_merge:
            merged_text = f"{previous.text} {chunk.text}"
            kept[-1] = Chunk(
                text=merged_text,
                heading=previous.heading,
                section_index=previous.section_index,
                chunk_index=previous.chunk_index,
                token_count=count_tokens(merged_text),
            )
        else:
            dropped += 1

    if dropped:
        logger.info(f"Dropped {dropped} fragment(s) below {min_tokens} tokens.")

    # Re-number so chunk_index stays contiguous after merges and drops.
    for i, chunk in enumerate(kept):
        chunk.chunk_index = i

    return kept
