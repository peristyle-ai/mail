"""
Hybrid search service for emails.

Combines three signals to find the most relevant emails for a query:
    1. Subject cosine similarity  (always available, on `emails.subject_embedding`)
    2. Chunk cosine similarity    (only for emails that have chunks; default
                                   Processed + Sent folders)
    3. Trigram keyword match      (cheap substring/typo-tolerant match; works
                                   everywhere — subject + chunk content)

Modes (via `mode=` query param on the route):
    hybrid   default — combines all three signals with a weighted sum
    subject  only subject cosine + subject trigram (no chunk work)
    chunks   only chunk cosine + chunk trigram (skips Inbox etc.)
    keyword  pure substring (ILIKE) — fastest, no embedding call

Backed by `emails.subject_embedding` (halfvec(1024), HNSW) and
`email_chunks.embedding` (halfvec(1024), HNSW) + `email_chunks.content`
GIN trigram index. PR1 created those; this service consumes them.

The query is embedded once per request via the same GPU server the
worker uses (`EmbeddingService`).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from app.db import get_db_connection
from app.services.embedding_service import EmbeddingService, EmbeddingError

logger = logging.getLogger(__name__)


# Scoring weights for the hybrid mode. Sum to 1.0.
WEIGHT_SUBJECT_COSINE = 0.30
WEIGHT_CHUNK_COSINE = 0.50
WEIGHT_TRIGRAM = 0.20

# Snippet length — return the first N chars of the matching chunk.
SNIPPET_MAX_CHARS = 240

# When a chunk matches, show this much context around the matched substring
# (for trigram mode). Falls back to the chunk head when no exact match.
SNIPPET_CONTEXT_CHARS = 80

# Module-level counter for embedding-server failures. Bumped every time
# `search()` falls back to keyword mode because the GPU server was
# unreachable. Operators can grep journalctl for the WARNING line (which
# includes the running total) or expose `gpu_fallback_count` via a debug
# endpoint to monitor GPU health.
gpu_fallback_count = 0


@dataclass
class SearchHit:
    """One result from the search."""
    email_id: int
    score: float
    snippet: Optional[str] = None
    snippet_highlight: Optional[str] = None  # matched substring (None for pure cosine)


@dataclass
class SearchResult:
    hits: List[SearchHit] = field(default_factory=list)
    mode: str = 'hybrid'
    query_embedding_ms: float = 0.0
    db_query_ms: float = 0.0
    # Total distinct emails that would match (across pages). For modes
    # that require the query embedding, this is computed alongside the
    # search itself (no extra embed call). For keyword mode, it's the
    # ILIKE COUNT. None when the count wasn't computed (e.g. keyword
    # mode with empty query).
    total: Optional[int] = None


def _make_snippet(content: str, query: str) -> Tuple[str, Optional[str]]:
    """Return (snippet, matched_substring).

    The snippet centers on the first match of any whitespace-split token
    from `query`, or the chunk head if nothing matches literally (so
    pure-cosine results still get *some* preview).
    """
    if not content:
        return '', None
    # Lowercase both for case-insensitive matching.
    content_lower = content.lower()
    # Try each query word.
    for word in re.findall(r'\w+', query):
        idx = content_lower.find(word)
        if idx >= 0:
            start = max(0, idx - SNIPPET_CONTEXT_CHARS)
            end = min(len(content), idx + len(word) + SNIPPET_CONTEXT_CHARS)
            snippet = content[start:end].strip()
            if start > 0:
                snippet = '\u2026' + snippet
            if end < len(content):
                snippet = snippet + '\u2026'
            return snippet[:SNIPPET_MAX_CHARS], content[idx:idx + len(word)]
    # No literal match — return the head of the chunk.
    head = content[:SNIPPET_MAX_CHARS].strip()
    if len(content) > SNIPPET_MAX_CHARS:
        head = head + '\u2026'
    return head, None


def _embed_query(service: EmbeddingService, query: str) -> List[float]:
    """Embed a search query. Returns a 1024-dim halfvec-ready list."""
    if not query or not query.strip():
        raise ValueError('query is empty')
    try:
        return service.embed_one(query.strip())
    except EmbeddingError:
        raise


def search(
    user_id: int,
    query: str,
    *,
    mode: str = 'hybrid',
    folder_id: Optional[int] = None,
    flag: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
    embedding_service: Optional[EmbeddingService] = None,
) -> SearchResult:
    """Run a search and return ranked hits.

    Args:
        user_id: search within this user's emails (folder ownership).
        query: free-text query.
        mode: 'hybrid' (default), 'subject', 'chunks', or 'keyword'.
        folder_id: optional folder filter.
        flag: optional 'read' / 'unread' / 'starred' filter.
        page / limit: pagination.
        embedding_service: optional injected service (used by tests).

    Returns:
        SearchResult with hits sorted by score desc.
    """
    import time
    result = SearchResult(mode=mode)
    if not query or not query.strip():
        return result

    service = embedding_service or EmbeddingService()
    t0 = time.monotonic()
    try:
        query_vec = _embed_query(service, query)
    except EmbeddingError as e:
        global gpu_fallback_count
        gpu_fallback_count += 1
        # Log at WARNING with the running total so a sustained outage
        # shows up clearly in journalctl (every line shows the
        # incrementing count). grep for `embedding server unavailable`
        # to count occurrences.
        logger.warning(
            "embedding server unavailable, falling back to keyword mode "
            "(q=%r, total_fallbacks=%d): %s",
            query[:60], gpu_fallback_count, e,
        )
        mode = 'keyword'
        result.mode = 'keyword'
        query_vec = None
    finally:
        if service is not embedding_service:
            service.close()
    result.query_embedding_ms = (time.monotonic() - t0) * 1000

    t0 = time.monotonic()
    if mode == 'keyword':
        hits = _keyword_search(user_id, query, folder_id, flag, page, limit)
    elif mode == 'subject':
        hits = _subject_search(user_id, query_vec, query, folder_id, flag, page, limit)
    elif mode == 'chunks':
        hits = _chunks_search(user_id, query_vec, query, folder_id, flag, page, limit)
    else:  # hybrid (default)
        hits = _hybrid_search(user_id, query_vec, query, folder_id, flag, page, limit)
    result.db_query_ms = (time.monotonic() - t0) * 1000
    result.hits = hits

    # Total across pages — mirrors what each mode actually matches.
    # Uses the same query_vec (no extra embed call) for semantic modes.
    try:
        if mode == 'keyword':
            result.total = _count_keyword(user_id, query, folder_id, flag)
        elif mode == 'subject':
            result.total = _count_subject(user_id, query_vec, query, folder_id, flag)
        elif mode == 'chunks':
            result.total = _count_chunks(user_id, query_vec, query, folder_id, flag)
        else:
            result.total = _count_hybrid(user_id, query_vec, query, folder_id, flag)
    except Exception as e:
        # Don't fail the search if counting fails — log and move on.
        # Clients can still paginate by incrementing page until hits
        # are empty.
        logger.warning("search count failed: %s", e)
        result.total = None

    return result


def _count_keyword(user_id, query, folder_id, flag):
    """ILIKE-only count. Single index scan, no embedding needed."""
    conn = get_db_connection()
    cursor = conn.cursor()
    where, params = _folder_clause(folder_id, flag, user_id)
    like = '%' + query + '%'
    cursor.execute(
        f'''SELECT COUNT(*) AS n
            FROM emails e
            JOIN folders f ON e.folder_id = f.id
            WHERE {where}
              AND (e.subject ILIKE %s OR e.body ILIKE %s)''',
        params + [like, like],
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row['n'] if row else 0


def _count_subject(user_id, query_vec, query, folder_id, flag):
    """Count emails that would match subject cosine + trigram + ILIKE."""
    conn = get_db_connection()
    cursor = conn.cursor()
    where, params = _folder_clause(folder_id, flag, user_id)
    like = '%' + query + '%'
    # Placeholders: query_vec, like (subject ILIKE), like (body ILIKE),
    # then WHERE params (sender_id, optional folder_id).
    sql_params = [query_vec, like, like] + params
    cursor.execute(
        f'''SELECT COUNT(DISTINCT e.id) AS n
            FROM emails e
            JOIN folders f ON e.folder_id = f.id
            WHERE {where}
              AND ((e.subject_embedding IS NOT NULL
                    AND (1 - (e.subject_embedding <=> %s::halfvec)) > 0.3)
                   OR e.subject ILIKE %s
                   OR e.body ILIKE %s)''',
        sql_params,
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row['n'] if row else 0


def _count_chunks(user_id, query_vec, query, folder_id, flag):
    """Count distinct emails that would match chunk cosine + trigram + ILIKE."""
    conn = get_db_connection()
    cursor = conn.cursor()
    where_parts = ['f.user_id = %s']
    params = [user_id]
    if folder_id is not None:
        where_parts.append('emails.folder_id = %s')
        params.append(folder_id)
    if flag == 'read':
        where_parts.append('emails.is_read = TRUE')
    elif flag == 'unread':
        where_parts.append('emails.is_read = FALSE')
    elif flag == 'starred':
        where_parts.append('emails.is_starred = TRUE')
    where = ' AND '.join(where_parts)
    like = '%' + query + '%'
    # Placeholders: query_vec, like (content ILIKE), then WHERE params.
    sql_params = [query_vec, like] + params
    cursor.execute(
        f'''SELECT COUNT(DISTINCT emails.id) AS n
            FROM emails
            JOIN folders f ON emails.folder_id = f.id
            JOIN email_chunks c ON c.email_id = emails.id
            WHERE {where}
              AND ((c.embedding IS NOT NULL
                    AND (1 - (c.embedding <=> %s::halfvec)) > 0.3)
                   OR c.content ILIKE %s)''',
        sql_params,
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row['n'] if row else 0


def _count_hybrid(user_id, query_vec, query, folder_id, flag):
    """Union of subject + chunk match counts. One query, no duplication.

    Uses two CTEs that mirror the actual hybrid search criteria
    (subject cosine + trigram + ILIKE on subject, same on chunks).
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    # Build the shared filter once; reuse for both branches.
    where_parts = ['f.user_id = %s']
    params = [user_id]
    if folder_id is not None:
        where_parts.append('emails.folder_id = %s')
        params.append(folder_id)
    if flag == 'read':
        where_parts.append('emails.is_read = TRUE')
    elif flag == 'unread':
        where_parts.append('emails.is_read = FALSE')
    elif flag == 'starred':
        where_parts.append('emails.is_starred = TRUE')
    base_where = ' AND '.join(where_parts)
    like = '%' + query + '%'
    # Placeholder order (all CTEs share one parameter stream):
    #   1..N. params  (subject_hits WHERE: sender_id, folder_id)
    #   N+1. query_vec  (subject cosine)
    #   N+2. like       (subject ILIKE)
    #   N+3. like       (body ILIKE)
    #   N+4..2N. params (chunk_hits WHERE: sender_id, folder_id)
    #   2N+1. query_vec (chunk cosine)
    #   2N+2. like      (chunk content ILIKE)
    sql_params = (params + [query_vec, like, like]
                  + params + [query_vec, like])
    cursor.execute(
        f'''WITH subject_hits AS (
                SELECT e.id FROM emails e
                JOIN folders f ON e.folder_id = f.id
                WHERE {base_where.replace('emails.', 'e.')}
                  AND ((e.subject_embedding IS NOT NULL
                        AND (1 - (e.subject_embedding <=> %s::halfvec)) > 0.3)
                       OR e.subject ILIKE %s
                       OR e.body ILIKE %s)
            ),
            chunk_hits AS (
                SELECT emails.id FROM emails
                JOIN folders f ON emails.folder_id = f.id
                JOIN email_chunks c ON c.email_id = emails.id
                WHERE {base_where}
                  AND ((c.embedding IS NOT NULL
                        AND (1 - (c.embedding <=> %s::halfvec)) > 0.3)
                       OR c.content ILIKE %s)
            )
            SELECT COUNT(*) FROM (
                SELECT id FROM subject_hits
                UNION
                SELECT id FROM chunk_hits
            ) u''',
        sql_params,
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row['count'] if row else 0


def _folder_clause(folder_id: Optional[int], flag: Optional[str], user_id: int) -> Tuple[str, list]:
    """Build the shared WHERE clause (everything except the query signal).
    
    Uses folder ownership (f.user_id) rather than sender_id, matching the
    authorization pattern used throughout the rest of the application.
    This ensures users can search both sent AND received emails.
    
    The caller must ensure the FROM clause includes:
        JOIN folders f ON e.folder_id = f.id
    """
    where = ['f.user_id = %s']
    params: list = [user_id]
    if folder_id is not None:
        where.append('e.folder_id = %s')
        params.append(folder_id)
    if flag == 'read':
        where.append('e.is_read = TRUE')
    elif flag == 'unread':
        where.append('e.is_read = FALSE')
    elif flag == 'starred':
        where.append('e.is_starred = TRUE')
    return ' AND '.join(where), params


def _keyword_search(user_id, query, folder_id, flag, page, limit):
    """Existing ILIKE behavior — fast, no embedding."""
    conn = get_db_connection()
    cursor = conn.cursor()
    where, params = _folder_clause(folder_id, flag, user_id)
    like = '%' + query + '%'
    cursor.execute(
        f'''SELECT e.id, e.subject, NULL::text AS snippet, 1.0::float AS score, NULL::text AS match
            FROM emails e
            JOIN folders f ON e.folder_id = f.id
            WHERE {where} AND (e.subject ILIKE %s OR e.body ILIKE %s)
            ORDER BY e.created_at DESC
            LIMIT %s OFFSET %s''',
        params + [like, like, limit, (page - 1) * limit],
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [
        SearchHit(email_id=r['id'], score=r['score'], snippet=None,
                  snippet_highlight=None)
        for r in rows
    ]


def _subject_search(user_id, query_vec, query, folder_id, flag, page, limit):
    """Cosine + trigram + ILIKE over `emails.subject_embedding` and `subject`.

    The ILIKE clause is what makes hybrid mode useful for emails that
    haven't been embedded yet (e.g., tests that create + search inline,
    or new emails before the worker catches up). Without it, the search
    would only find emails that have subject_embedding, missing every
    fresh row.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    where, params = _folder_clause(folder_id, flag, user_id)
    # ILIKE pattern uses the same `query` string.
    like = '%' + query + '%'
    # SQL placeholders (in order):
    #   1. query_vec  (cosine_score)
    #   2. query      (trgm_score)
    #   3. query_vec  (combined_score cosine term)
    #   4. WEIGHT_SUBJECT_COSINE
    #   5. query      (combined_score trgm term)
    #   6. WEIGHT_TRIGRAM
    #   7. like       (ILIKE fallback)
    #   8+. WHERE clause params
    #   N-1. limit, offset
    sql_params = [query_vec, query,
                  query_vec, WEIGHT_SUBJECT_COSINE,
                  query, WEIGHT_TRIGRAM, like] + params + [like, like, limit, (page - 1) * limit]
    cursor.execute(
        f'''SELECT e.id,
                   COALESCE((1 - (e.subject_embedding <=> %s::halfvec))::float, 0)
                       AS cosine_score,
                   COALESCE(similarity(e.subject, %s), 0) AS trgm_score,
                   (COALESCE((1 - (e.subject_embedding <=> %s::halfvec)), 0) * %s
                    + COALESCE(similarity(e.subject, %s), 0) * %s
                    + CASE WHEN e.subject ILIKE %s THEN 0.5 ELSE 0 END
                   )::float AS combined_score,
                   NULL::text AS snippet,
                   NULL::text AS match
            FROM emails e
            JOIN folders f ON e.folder_id = f.id
            WHERE {where}
              AND (e.subject_embedding IS NOT NULL
                   OR e.subject ILIKE %s
                   OR e.body ILIKE %s)
            ORDER BY combined_score DESC
            LIMIT %s OFFSET %s''',
        sql_params,
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [
        SearchHit(email_id=r['id'], score=r['combined_score'] or 0.0,
                  snippet=None, snippet_highlight=None)
        for r in rows
    ]


def _chunks_search(user_id, query_vec, query, folder_id, flag, page, limit):
    """Cosine + trigram + ILIKE over `email_chunks`. Snippet = top chunk."""
    conn = get_db_connection()
    cursor = conn.cursor()
    # The chunks table joins to emails via email_id. Build the WHERE
    # against emails directly (no `e.` alias since the inner FROM uses
    # explicit JOINs).
    where_parts = ['f.user_id = %s']
    params: list = [user_id]
    if folder_id is not None:
        where_parts.append('emails.folder_id = %s')
        params.append(folder_id)
    if flag == 'read':
        where_parts.append('emails.is_read = TRUE')
    elif flag == 'unread':
        where_parts.append('emails.is_read = FALSE')
    elif flag == 'starred':
        where_parts.append('emails.is_starred = TRUE')
    where = ' AND '.join(where_parts)
    like = '%' + query + '%'

    sql_params = [query_vec, query,
                  query_vec, WEIGHT_CHUNK_COSINE,
                  query, WEIGHT_TRIGRAM, like] + params + [like, limit, (page - 1) * limit]
    cursor.execute(
        f'''WITH scored AS (
                SELECT c.email_id, c.content,
                       COALESCE((1 - (c.embedding <=> %s::halfvec))::float, 0)
                           AS sim_score,
                       COALESCE(similarity(c.content, %s), 0) AS trgm_score,
                       (COALESCE((1 - (c.embedding <=> %s::halfvec)), 0) * %s
                        + COALESCE(similarity(c.content, %s), 0) * %s
                        + CASE WHEN c.content ILIKE %s THEN 0.5 ELSE 0 END
                       )::float AS combined_score
                FROM email_chunks c
                JOIN emails ON emails.id = c.email_id
                JOIN folders f ON emails.folder_id = f.id
                WHERE {where}
                  AND (c.embedding IS NOT NULL OR c.content ILIKE %s)
            ),
            ranked AS (
                SELECT email_id, content, combined_score,
                       ROW_NUMBER() OVER (PARTITION BY email_id
                                          ORDER BY combined_score DESC) AS rn
                FROM scored
            )
            SELECT email_id, content AS snippet, combined_score AS score
            FROM ranked WHERE rn = 1
            ORDER BY combined_score DESC
            LIMIT %s OFFSET %s''',
        sql_params,
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    hits = []
    for r in rows:
        snippet, match = _make_snippet(r['snippet'] or '', query)
        hits.append(SearchHit(
            email_id=r['email_id'], score=r['score'] or 0.0,
            snippet=snippet, snippet_highlight=match,
        ))
    return hits


def _hybrid_search(user_id, query_vec, query, folder_id, flag, page, limit):
    """Combine subject + chunks. Fetch a wider window from each source,
    merge + dedupe + re-rank."""
    # Fetch 3x the limit from each source so we have room to merge.
    window = min(limit * 3, 100)
    subj_hits = _subject_search(user_id, query_vec, query, folder_id, flag,
                                page=1, limit=window)
    chunk_hits = _chunks_search(user_id, query_vec, query, folder_id, flag,
                                page=1, limit=window)
    # Merge by email_id, taking max score, preserving the snippet from chunks.
    merged: Dict[int, SearchHit] = {}
    for h in subj_hits:
        merged[h.email_id] = h
    for h in chunk_hits:
        if h.email_id in merged:
            existing = merged[h.email_id]
            existing.score = max(existing.score, h.score)
            if h.snippet:
                existing.snippet = h.snippet
                existing.snippet_highlight = h.snippet_highlight
        else:
            merged[h.email_id] = h
    # Sort + paginate.
    hits = sorted(merged.values(), key=lambda h: h.score, reverse=True)
    start = (page - 1) * limit
    return hits[start:start + limit]
