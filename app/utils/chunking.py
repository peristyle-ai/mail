"""
Sentence-aware sliding-window text chunker.

Used by the embedding worker to split an email body into ~target_chars-sized
chunks with `overlap_chars` of overlap between adjacent chunks. Splits prefer
sentence boundaries when one is found inside the target window, falling back
to whitespace, falling back to a hard cut.

Why not NLTK / a tokenizer? Two reasons:
    1. NLTK isn't a project dep, and pulling punkt for one splitter is
       overkill given email bodies are short and structured.
    2. A deterministic, regex-only splitter has zero cold-start cost and
       doesn't break when the venv is rebuilt without internet access.

The output is consumed by `app.services.embedding_service.EmbeddingService`
and persisted to `email_chunks` (see db/migrations/003_*.sql).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional


# Sentence-end punctuation followed by whitespace + capital letter / closing
# bracket / quote. Catches most English emails; non-Latin scripts fall
# through to the whitespace split.
_SENT_END = re.compile(r'(?<=[\.!?])\s+(?=[A-Z\'"(\[])')

# Whitespace runs (we split on these for the fallback).
_WS = re.compile(r'\s+')

# Cap the body length we actually chunk. Most emails are well under
# 50 KB; the long tail (HTML newsletters with inline CSS / Base64
# images, accidentally-pasted logs) can hit 2-3 MB and would chew
# through hundreds of chunks per email. The first 50 KB usually
# contain the readable content; the rest is payload. Truncate at
# MAX_BODY_CHARS to keep per-email work bounded.
MAX_BODY_CHARS = 50_000

# Max chunks per email. Another bound — an email that legitimately
# needs more than this many 800-char chunks is almost certainly an
# outlier that should be re-categorized manually. Stops the worker
# from spending hours on a single row.
MAX_CHUNKS_PER_EMAIL = 50


@dataclass(frozen=True)
class TextChunk:
    """One chunk of an email body. `index` is 0-based position in the email."""
    index: int
    text: str

    @property
    def token_count(self) -> int:
        """Rough token estimate: whitespace-separated words.

        Not exact (no tokenizer) but close enough for monitoring/observability.
        The vector store doesn't depend on this number.
        """
        if not self.text:
            return 0
        return len(self.text.split())


def _strip_html(text: str) -> str:
    """Crude HTML stripper for chunking purposes only.

    We do NOT use this for rendering — the API serves the original HTML via
    `body_html`. We only need a readable plaintext approximation to embed.
    Strips tags, decodes the handful of entities that actually appear in
    emails (&nbsp;, &amp;, &lt;, &gt;, &quot;, &#39;), collapses whitespace.
    """
    if not text:
        return ''
    # Drop script/style blocks wholesale (their text is rarely useful).
    text = re.sub(r'<(script|style)\b[^>]*>.*?</\1>', ' ', text, flags=re.DOTALL | re.IGNORECASE)
    # Replace block-level tags with a space (preserves sentence breaks).
    text = re.sub(r'</?(p|div|br|tr|li|h[1-6])\b[^>]*>', ' ', text, flags=re.IGNORECASE)
    # Drop remaining tags.
    text = re.sub(r'<[^>]+>', '', text)
    # Decode the common entities.
    text = (
        text.replace('&nbsp;', ' ')
            .replace('&amp;', '&')
            .replace('&lt;', '<')
            .replace('&gt;', '>')
            .replace('&quot;', '"')
            .replace('&#39;', "'")
    )
    # Collapse whitespace.
    text = _WS.sub(' ', text).strip()
    return text


def chunk_email(
    body: str,
    body_html: str = '',
    target_chars: int = 800,
    overlap_chars: int = 100,
    max_body_chars: int = MAX_BODY_CHARS,
    max_chunks: int = MAX_CHUNKS_PER_EMAIL,
) -> List[TextChunk]:
    """Split an email body into overlapping chunks.

    Args:
        body: plaintext body (preferred when present).
        body_html: HTML body, used as fallback if `body` is empty.
        target_chars: rough target size per chunk. Actual chunks may be
            shorter (last chunk, short emails) but rarely longer because we
            always cut at a sentence boundary when one is available.
        overlap_chars: how much to repeat at the start of the next chunk so
            semantic context isn't lost at the boundary. 0 disables overlap.
        max_body_chars: hard cap on input length. Anything past this point
            is truncated — most emails are short, and the long tail is
            usually HTML payload / Base64 images that don't help semantic
            search. Bounds the work per email.
        max_chunks: hard cap on number of chunks produced. Emails that
            exceed this are returned with the first N chunks (no
            summarization).

    Returns:
        List[TextChunk], 0-indexed, in document order. Empty list when the
        email has no usable content.
    """
    text = body.strip() if body else _strip_html(body_html or '')
    if not text:
        return []
    if len(text) > max_body_chars:
        # Truncate at the nearest sentence boundary inside the cap so we
        # don't slice mid-word. If no boundary, hard-cut.
        truncated = text[:max_body_chars]
        boundary = max(truncated.rfind('. '), truncated.rfind('! '),
                       truncated.rfind('? '))
        if boundary > max_body_chars // 2:
            text = truncated[:boundary + 1]
        else:
            text = truncated

    # Collapse runs of whitespace so chunk size math is predictable.
    text = _WS.sub(' ', text).strip()

    # Short-circuit: a single chunk when the email fits.
    if len(text) <= target_chars:
        return [TextChunk(index=0, text=text)]

    chunks: List[TextChunk] = []
    cursor = 0
    n = len(text)
    while cursor < n:
        end = min(cursor + target_chars, n)
        # Try to back up to a sentence boundary inside [cursor+overlap, end].
        if end < n:
            window = text[cursor + overlap_chars:end]
            boundary = None
            for m in _SENT_END.finditer(window):
                # Position of the whitespace that starts a new sentence.
                boundary = cursor + overlap_chars + m.end() - 1  # the space
            if boundary and boundary > cursor + overlap_chars:
                end = boundary + 1  # include the trailing space
            else:
                # Fall back: back up to the last whitespace in the window.
                ws = None
                for m in _WS.finditer(window):
                    ws = cursor + overlap_chars + m.end()
                if ws and ws > cursor + overlap_chars:
                    end = ws
        chunk_text = text[cursor:end].strip()
        if chunk_text:
            chunks.append(TextChunk(index=len(chunks), text=chunk_text))
            if len(chunks) >= max_chunks:
                break
        if end >= n:
            break
        # Advance with overlap.
        cursor = max(end - overlap_chars, cursor + 1)
    return chunks


def chunk_texts(texts: Iterable[str]) -> List[str]:
    """Helper for tests / callers that want just the strings."""
    return [c.text for c in (
        TextChunk(index=i, text=t) for i, t in enumerate(texts)
    )]
