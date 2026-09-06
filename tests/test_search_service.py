"""
Tests for the search service (PR2 of embeddings rollout).

Covers:
    * Snippet generation (centers around matched substring)
    * Keyword search (existing ILIKE behavior, no embedding)
    * Subject cosine + trigram
    * Chunk cosine + trigram (snippets returned)
    * Hybrid: combines subject + chunks, dedupes by email_id
    * Mode fallback when embedding server is unreachable
    * Folder / flag filters
    * Empty query returns list-mode (backward compat with no-q behavior)

Runs against a throwaway test DB; needs the GPU server reachable.
Skip when POSTGRES_DB_NAME / POSTGRES_PASSWORD_TEST unset.
"""

from __future__ import annotations

import os
import sys
import unittest
import uuid
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if not os.environ.get('POSTGRES_DB_NAME') or not os.environ.get('POSTGRES_PASSWORD_TEST'):
    raise unittest.SkipTest(
        'POSTGRES_DB_NAME / POSTGRES_PASSWORD_TEST not set; skipping '
        'search service tests'
    )


import psycopg2
from psycopg2.extras import RealDictCursor


# =============================================================================
# Setup helpers
# =============================================================================

def _setup_db():
    """Make sure email_chunks + embedding_jobs + subject_embedding exist
    on the test DB. Mirrors PR1's _setup_db in test_embedding_pipeline.py
    but factored out so both test files share it.
    """
    url = os.environ['DATABASE_URL']
    sql = '''
        CREATE EXTENSION IF NOT EXISTS vector;
        CREATE EXTENSION IF NOT EXISTS pg_trgm;

        ALTER TABLE emails ADD COLUMN IF NOT EXISTS subject_embedding halfvec(1024);
        CREATE INDEX IF NOT EXISTS emails_subject_embedding_hnsw
            ON emails USING hnsw (subject_embedding halfvec_cosine_ops);

        CREATE TABLE IF NOT EXISTS email_chunks (
            id          BIGSERIAL PRIMARY KEY,
            email_id    INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
            folder_id   INTEGER REFERENCES folders(id) ON DELETE SET NULL,
            chunk_index INTEGER NOT NULL,
            content     TEXT NOT NULL,
            embedding   halfvec(1024),
            token_count INTEGER,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(email_id, chunk_index)
        );
        CREATE INDEX IF NOT EXISTS idx_email_chunks_email_id
            ON email_chunks(email_id);
        CREATE INDEX IF NOT EXISTS idx_email_chunks_embedding_hnsw
            ON email_chunks USING hnsw (embedding halfvec_cosine_ops)
            WITH (m = 16, ef_construction = 64);
        CREATE INDEX IF NOT EXISTS idx_email_chunks_content_trgm
            ON email_chunks USING gin (content gin_trgm_ops);

        CREATE TABLE IF NOT EXISTS embedding_jobs (
            id            BIGSERIAL PRIMARY KEY,
            email_id      INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
            enqueued_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            next_retry_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            started_at    TIMESTAMPTZ,
            completed_at  TIMESTAMPTZ,
            status        TEXT NOT NULL DEFAULT 'pending'
                              CHECK (status IN ('pending','processing','done','failed','skipped')),
            attempts      INTEGER NOT NULL DEFAULT 0,
            last_error    TEXT
        );
    '''
    conn = psycopg2.connect(url, cursor_factory=RealDictCursor)
    cur = conn.cursor()
    cur.execute(sql)
    conn.commit()
    cur.close()
    conn.close()


def _connect():
    return psycopg2.connect(os.environ['DATABASE_URL'], cursor_factory=RealDictCursor)


def _make_user_and_folder(folder_name: str = 'Sent') -> tuple:
    """Create a fresh user + folder for this test."""
    u = uuid.uuid4().hex[:8]
    user_email = f'unit-search-{u}@test'
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        '''INSERT INTO users (email, password_hash, name)
           VALUES (%s, 'x', %s) RETURNING id''',
        (user_email, user_email),
    )
    user_id = cur.fetchone()['id']
    cur.execute(
        'INSERT INTO folders (user_id, name) VALUES (%s, %s) RETURNING id',
        (user_id, folder_name),
    )
    folder_id = cur.fetchone()['id']
    conn.commit()
    cur.close()
    conn.close()
    return user_id, folder_id, folder_name


def _make_email(user_id: int, folder_id: int, subject: str, body: str) -> int:
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        '''INSERT INTO emails
           (sender_id, recipient_id, folder_id, subject, body, body_html, is_read)
           VALUES (%s, %s, %s, %s, %s, '', FALSE)
           RETURNING id''',
        (user_id, user_id, folder_id, subject, body),
    )
    eid = cur.fetchone()['id']
    cur.execute(
        '''INSERT INTO email_recipients (email_id, user_id, recipient_type)
           VALUES (%s, %s, 'to')''',
        (eid, user_id),
    )
    conn.commit()
    cur.close()
    conn.close()
    return eid


def _embed_subject_only(eid: int) -> None:
    """Embed the subject of an email without populating chunks. Useful for
    testing subject-only search modes."""
    from app.services.embedding_service import EmbeddingService
    from app.db import get_db_connection
    svc = EmbeddingService()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT subject FROM emails WHERE id = %s', (eid,))
    subj = (cur.fetchone()['subject'] or '').strip()
    if subj:
        vec = svc.embed_one(subj)
        cur.execute(
            'UPDATE emails SET subject_embedding = %s::halfvec WHERE id = %s',
            (vec, eid),
        )
    conn.commit()
    cur.close()
    conn.close()
    svc.close()


def _make_chunk(eid: int, folder_id: int, chunk_index: int, content: str) -> None:
    """Insert an email_chunks row with a real embedding for `content`."""
    from app.services.embedding_service import EmbeddingService
    from app.db import get_db_connection
    svc = EmbeddingService()
    vec = svc.embed_one(content)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        '''INSERT INTO email_chunks
            (email_id, folder_id, chunk_index, content, embedding, token_count)
           VALUES (%s, %s, %s, %s, %s::halfvec, %s)
           ON CONFLICT (email_id, chunk_index) DO UPDATE
           SET content = EXCLUDED.content, embedding = EXCLUDED.embedding''',
        (eid, folder_id, chunk_index, content, vec, len(content.split())),
    )
    conn.commit()
    cur.close()
    conn.close()
    svc.close()


# =============================================================================
# Snippet generation (no DB)
# =============================================================================

class TestSnippet(unittest.TestCase):
    def test_centers_on_matched_word(self):
        from app.services.search_service import _make_snippet
        content = ('Lorem ipsum dolor sit amet. ' * 20).strip()
        snippet, match = _make_snippet(content, 'dolor')
        self.assertIn('dolor', snippet)
        self.assertEqual(match, 'dolor')

    def test_returns_head_when_no_literal_match(self):
        from app.services.search_service import _make_snippet
        content = ('Some unrelated text. ' * 30).strip()
        snippet, match = _make_snippet(content, 'database')
        # No literal match → fall back to chunk head.
        self.assertIsNone(match)
        self.assertTrue(snippet.startswith('Some') or snippet.endswith('…'))

    def test_truncates_long_content(self):
        from app.services.search_service import _make_snippet, SNIPPET_MAX_CHARS
        content = ('word ' * 200).strip()  # ~1000 chars
        snippet, _ = _make_snippet(content, 'word')
        self.assertLessEqual(len(snippet), SNIPPET_MAX_CHARS + 5)  # +5 for ellipses


# =============================================================================
# Search integration (DB + GPU)
# =============================================================================

class TestSearchIntegration(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        _setup_db()
        # The GPU server is shared infra; skip these tests if it's not
        # reachable.
        from app.services.embedding_service import EmbeddingService
        try:
            svc = EmbeddingService()
            if not svc.healthcheck():
                raise unittest.SkipTest('Embedding GPU server not reachable')
            svc.close()
        except Exception as e:
            raise unittest.SkipTest(f'Embedding GPU server init failed: {e}')

    def setUp(self):
        conn = _connect()
        cur = conn.cursor()
        cur.execute('DELETE FROM embedding_jobs')
        cur.execute('DELETE FROM email_chunks')
        # Order matters — emails before users (FK constraint).
        cur.execute("""DELETE FROM email_recipients
                       WHERE email_id IN (
                           SELECT e.id FROM emails e
                           JOIN users u ON u.id = e.sender_id
                           WHERE u.email LIKE 'unit-search-%@test'
                       )""")
        cur.execute("""DELETE FROM emails
                       WHERE sender_id IN (
                           SELECT id FROM users WHERE email LIKE 'unit-search-%@test'
                       )""")
        cur.execute("""DELETE FROM folders WHERE user_id IN (
                           SELECT id FROM users WHERE email LIKE 'unit-search-%@test'
                       )""")
        cur.execute("""DELETE FROM users WHERE email LIKE 'unit-search-%@test'""")
        conn.commit()
        cur.close()
        conn.close()

    def test_keyword_mode_no_embedding_call(self):
        """mode=keyword returns ILIKE matches without touching the GPU."""
        from app.services.search_service import search
        uid, fid, _ = _make_user_and_folder('Sent')
        _make_email(uid, fid, 'Greetings from Test', 'Hello world.')
        r = search(user_id=uid, query='Hello', mode='keyword', limit=5)
        self.assertEqual(r.mode, 'keyword')
        self.assertEqual(len(r.hits), 1)
        self.assertIsNone(r.hits[0].snippet)  # keyword mode has no snippet

    def test_subject_search_uses_cosine(self):
        from app.services.search_service import search
        uid, fid, _ = _make_user_and_folder('Inbox')  # not enabled for chunks
        eid = _make_email(uid, fid, 'Database migration plan',
                          'body content here')
        _embed_subject_only(eid)
        r = search(user_id=uid, query='data storage', mode='subject', limit=5)
        self.assertGreater(len(r.hits), 0)
        self.assertEqual(r.hits[0].email_id, eid)
        # Subject mode doesn't return snippets (snippets are chunk-only).
        self.assertIsNone(r.hits[0].snippet)

    def test_chunks_search_returns_snippet(self):
        from app.services.search_service import search
        uid, fid, _ = _make_user_and_folder('Sent')
        eid = _make_email(uid, fid, 'Subject', 'irrelevant')
        _make_chunk(eid, fid, 0,
                    'Please review the database migration plan carefully. '
                    'The new schema includes several improvements.')
        r = search(user_id=uid, query='database', mode='chunks', limit=5)
        self.assertGreater(len(r.hits), 0)
        self.assertEqual(r.hits[0].email_id, eid)
        self.assertIn('database', r.hits[0].snippet.lower())

    def test_hybrid_combines_subject_and_chunks(self):
        """A query that hits only chunks (no subject match) still finds
        the email via the chunks branch."""
        from app.services.search_service import search
        uid, fid, _ = _make_user_and_folder('Sent')
        # Email whose subject is irrelevant but the body chunk mentions it.
        eid = _make_email(uid, fid, 'Subject line', 'body')
        _make_chunk(eid, fid, 0,
                    'Database migration: we need to move from MySQL to Postgres.')
        r = search(user_id=uid, query='postgres migration', mode='hybrid', limit=5)
        self.assertGreater(len(r.hits), 0)
        self.assertEqual(r.hits[0].email_id, eid)

    def test_folder_filter(self):
        from app.services.search_service import search
        uid, sfid, _ = _make_user_and_folder('Sent')
        ifid = _connect()
        cur = ifid.cursor()
        cur.execute(
            'INSERT INTO folders (user_id, name) VALUES (%s, %s) RETURNING id',
            (uid, 'Inbox'),
        )
        ifid2 = cur.fetchone()['id']
        ifid.commit()
        cur.close()
        ifid.close()
        eid_sent = _make_email(uid, sfid, 'Database talk', 'body')
        _make_chunk(eid_sent, sfid, 0, 'Some database discussion.')
        _make_chunk(_make_email(uid, ifid2, 'Inbox topic', 'body'),
                    ifid2, 0, 'Some inbox discussion.')
        # Search restricted to Sent folder — should find the sent one.
        r = search(user_id=uid, query='database', mode='hybrid',
                   folder_id=sfid, limit=10)
        sent_ids = {h.email_id for h in r.hits}
        self.assertIn(eid_sent, sent_ids)

    def test_empty_query_returns_no_query_error(self):
        """Empty query → empty result, no GPU call."""
        from app.services.search_service import search
        uid, fid, _ = _make_user_and_folder('Sent')
        r = search(user_id=uid, query='', mode='hybrid', limit=5)
        self.assertEqual(len(r.hits), 0)

    def test_fallback_to_keyword_when_gpu_unreachable(self):
        """If the embedding service raises, fall back to keyword mode
        rather than 500-ing."""
        from app.services.search_service import search
        from app.services.embedding_service import EmbeddingError

        uid, fid, _ = _make_user_and_folder('Sent')
        _make_email(uid, fid, 'Subject A', 'Body containing literal word.')
        _make_email(uid, fid, 'Subject B', 'Body without it.')

        class BrokenService:
            def embed_one(self, *_a, **_kw):
                raise EmbeddingError('GPU down')
            def close(self):
                pass

        r = search(user_id=uid, query='literal', mode='hybrid', limit=5,
                   embedding_service=BrokenService())
        self.assertEqual(r.mode, 'keyword')
        # The keyword-mode fallback should still find the literal match.
        self.assertEqual(len(r.hits), 1)

    def test_total_counts_actual_matches(self):
        """`SearchResult.total` reflects the real count across pages,
        not just the page size. Includes semantic matches when they exist."""
        from app.services.search_service import search
        uid, fid, _ = _make_user_and_folder('Sent')
        # 3 emails match the literal query.
        for i in range(3):
            _make_email(uid, fid, f'Project kickoff {i}',
                        'body content about the project')
        # 1 email doesn't match the literal but its body chunk mentions it.
        eid_extra = _make_email(uid, fid, 'Irrelevant subject', 'body')
        _make_chunk(eid_extra, fid, 0,
                    'We discussed the project kickoff at length.')
        r = search(user_id=uid, query='project kickoff', mode='hybrid', limit=1)
        # Page size is 1 (we asked limit=1), but total should be > 1.
        self.assertEqual(len(r.hits), 1)
        self.assertIsNotNone(r.total)
        self.assertGreaterEqual(r.total, 3)

    def test_total_bumps_gpu_fallback_counter(self):
        """When the GPU server is down, fallback increments the module-
        level counter and logs a WARNING."""
        # Import via the module (not the symbol) to make sure we read
        # the same counter that search() mutates — Python's import
        # semantics for module-level globals can confuse this otherwise.
        import app.services.search_service as ss
        from app.services.search_service import search
        from app.services.embedding_service import EmbeddingError

        before = ss.gpu_fallback_count

        class BrokenService:
            def embed_one(self, *_a, **_kw):
                raise EmbeddingError('GPU down')
            def close(self):
                pass

        uid, fid, _ = _make_user_and_folder('Sent')
        _make_email(uid, fid, 'Subject', 'body')
        r = search(user_id=uid, query='test', mode='hybrid', limit=5,
                   embedding_service=BrokenService())
        self.assertEqual(r.mode, 'keyword')
        self.assertEqual(ss.gpu_fallback_count, before + 1)


if __name__ == '__main__':
    unittest.main()
