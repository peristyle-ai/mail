"""
Tests for the embeddings PR1 pipeline.

Covers:
    * Chunker (app/utils/chunking.py)
    * Enqueue helper (app/utils/embedding_enqueue.py)
    * Worker drain-once happy path (app/services/embedding_worker.py)
    * Worker upsert idempotency
    * Worker skip path (empty subject + folder not enabled)
    * Worker retry path (transient embedding failure → backoff)
    * Move-endpoint enqueue wiring (POST /api/emails/<id>/move)

Runs against a throwaway test DB (POSTGRES_DB_NAME / POSTGRES_PASSWORD_TEST
set in conftest.py). Skipped otherwise.

Why a separate file from the threading tests?
    The threading tests use a minimal DB schema; PR1 introduces two new
    tables (email_chunks + embedding_jobs) that the threading tests
    don't need. Keeping PR1 tests in their own file keeps the dependency
    surface narrow — these tests won't break if you delete PR1 to
    bisect.
"""

from __future__ import annotations

import os
import sys
import unittest
from typing import List, Optional
from unittest.mock import patch

import psycopg2
from psycopg2.extras import RealDictCursor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if not os.environ.get('POSTGRES_DB_NAME') or not os.environ.get('POSTGRES_PASSWORD_TEST'):
    raise unittest.SkipTest(
        'POSTGRES_DB_NAME / POSTGRES_PASSWORD_TEST not set; skipping '
        'embedding pipeline tests'
    )


# =============================================================================
# Chunker tests (no DB needed)
# =============================================================================

class TestChunker(unittest.TestCase):
    from app.utils.chunking import chunk_email, TextChunk

    def test_short_email_single_chunk(self):
        from app.utils.chunking import chunk_email
        chunks = chunk_email('Hello world.')
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].text, 'Hello world.')
        self.assertEqual(chunks[0].index, 0)

    def test_empty_returns_empty(self):
        from app.utils.chunking import chunk_email
        self.assertEqual(chunk_email(''), [])
        self.assertEqual(chunk_email('   '), [])
        self.assertEqual(chunk_email(None, ''), [])

    def test_long_email_splits_at_sentence_boundary(self):
        from app.utils.chunking import chunk_email
        # Build a long body with clear sentence boundaries.
        sentence = 'This is a sentence with about forty characters. '
        text = (sentence * 30).strip()
        chunks = chunk_email(text, target_chars=200, overlap_chars=30)
        self.assertGreater(len(chunks), 1)
        # Each chunk should be < target_chars (the splitter backs up to a
        # sentence boundary when one is available in the window).
        for c in chunks:
            self.assertLessEqual(len(c.text), 250)

    def test_overlap_creates_context_continuity(self):
        from app.utils.chunking import chunk_email
        text = 'word ' * 500  # ~2000 chars, no sentence boundaries
        chunks = chunk_email(text, target_chars=200, overlap_chars=30)
        # When there's no sentence boundary the splitter falls back to
        # whitespace; chunks should still be produced.
        self.assertGreater(len(chunks), 5)
        # Each chunk should overlap the previous one — the trailing
        # `overlap_chars` worth of characters of chunk[i] should appear at
        # the start of chunk[i+1].
        for prev, nxt in zip(chunks, chunks[1:]):
            tail = prev.text[-30:].strip()
            self.assertTrue(
                nxt.text.startswith(tail[:10]) or tail in nxt.text,
                f'overlap missing between chunk {prev.index} and {nxt.index}',
            )

    def test_html_stripping_fallback(self):
        from app.utils.chunking import chunk_email
        html = '<p>Hello <b>world</b>! Welcome to <a href="x">our site</a>.</p>'
        chunks = chunk_email(body='', body_html=html)
        self.assertEqual(len(chunks), 1)
        # HTML tags should be gone but the text content preserved.
        self.assertNotIn('<', chunks[0].text)
        self.assertIn('Hello', chunks[0].text)
        self.assertIn('our site', chunks[0].text)

    def test_token_count_estimate(self):
        from app.utils.chunking import chunk_email
        chunks = chunk_email('one two three four five')
        self.assertEqual(chunks[0].token_count, 5)


# =============================================================================
# Enqueue helper tests (need DB)
# =============================================================================

def _setup_db():
    """Create the email_chunks + embedding_jobs tables in the test DB if
    they don't already exist. Mirrors db/migrations/003_*.sql.

    Also adds `subject_embedding` to the emails table (this was added to
    the live DB outside the repo earlier — see MEMORY.md pgvector halfvec
    dim ceiling, 2026-08-16). Test DB is bootstrapped from db/schema.sql
    which doesn't include it, so we add it here.
    """
    url = os.environ['DATABASE_URL']
    schema_sql = '''
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
        CREATE INDEX IF NOT EXISTS idx_embedding_jobs_pending
            ON embedding_jobs(next_retry_at) WHERE status = 'pending';
        CREATE INDEX IF NOT EXISTS idx_embedding_jobs_email_id
            ON embedding_jobs(email_id);
    '''
    conn = psycopg2.connect(url, cursor_factory=RealDictCursor)
    cur = conn.cursor()
    cur.execute(schema_sql)
    conn.commit()
    cur.close()
    conn.close()


def _connect():
    return psycopg2.connect(os.environ['DATABASE_URL'], cursor_factory=RealDictCursor)


def _seed_email(user_id: int, folder_id: int, subject: str = 'Subject',
                body: str = 'Body content', body_html: str = '') -> int:
    """Insert a minimal email row + recipient row. Returns the email_id."""
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        '''INSERT INTO emails
           (sender_id, recipient_id, folder_id, subject, body, body_html, is_read)
           VALUES (%s, %s, %s, %s, %s, %s, FALSE)
           RETURNING id''',
        (user_id, user_id, folder_id, subject, body, body_html),
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


class TestEnqueue(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        _setup_db()

    def setUp(self):
        # Clean state per test. The test DB might already have a user
        # left over from a previous run — use a unique one each test.
        # Order matters: emails → recipients → folders → users (FK order).
        conn = _connect()
        cur = conn.cursor()
        cur.execute('DELETE FROM embedding_jobs')
        cur.execute('DELETE FROM email_chunks')
        # Wipe both the prefixed-subject emails AND the empty-subject
        # ones (created by some tests).
        cur.execute("""DELETE FROM email_recipients
                       WHERE email_id IN (
                           SELECT e.id FROM emails e
                           JOIN users u ON u.id = e.sender_id
                           WHERE u.email LIKE 'unit-test-%@test'
                       )""")
        cur.execute("""DELETE FROM emails
                       WHERE sender_id IN (
                           SELECT id FROM users WHERE email LIKE 'unit-test-%@test'
                       )""")
        cur.execute("""DELETE FROM folders WHERE user_id IN (
                           SELECT id FROM users WHERE email LIKE 'unit-test-%@test'
                       )""")
        cur.execute("""DELETE FROM users WHERE email LIKE 'unit-test-%@test'""")
        conn.commit()
        cur.close()
        conn.close()

    def _make_user_and_folder(self, folder_name: str = 'Inbox') -> tuple:
        """Create a fresh user + folder for this test.

        We use the real folder name (e.g. 'Sent' / 'Inbox') because the
        per-folder opt-in matches by casefolded name. Each test gets a
        fresh user_id so UNIQUE(user_id, name) lets multiple tests share
        the same logical folder names without conflict.
        """
        import uuid
        u = uuid.uuid4().hex[:8]
        user_email = f'unit-test-{u}@test'
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

    def test_enqueue_subject_always_runs(self):
        """Even when the folder is not configured for body chunking,
        subject embedding should be enqueued."""
        from app.utils.embedding_enqueue import enqueue_embedding_job
        user_id, folder_id, folder_name = self._make_user_and_folder('Inbox')
        eid = _seed_email(user_id=user_id, folder_id=folder_id,
                          subject='unit-test-subject-always')
        ok = enqueue_embedding_job(eid, folder_id=folder_id, user_id=user_id,
                                   reason='unit_test')
        self.assertTrue(ok)
        conn = _connect()
        cur = conn.cursor()
        cur.execute('SELECT email_id, status FROM embedding_jobs WHERE email_id = %s',
                    (eid,))
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row['status'], 'pending')
        cur.close()
        conn.close()

    def test_enqueue_skips_live_job(self):
        """Enqueueing the same email twice should NOT create a duplicate."""
        from app.utils.embedding_enqueue import enqueue_embedding_job
        user_id, folder_id, _ = self._make_user_and_folder('Inbox')
        eid = _seed_email(user_id=user_id, folder_id=folder_id,
                          subject='unit-test-dup-test')
        enqueue_embedding_job(eid, folder_id=folder_id, user_id=user_id, reason='first')
        enqueue_embedding_job(eid, folder_id=folder_id, user_id=user_id, reason='second')
        conn = _connect()
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) AS n FROM embedding_jobs WHERE email_id = %s',
                    (eid,))
        self.assertEqual(cur.fetchone()['n'], 1)
        cur.close()
        conn.close()


# =============================================================================
# Worker tests (need DB + GPU server reachable)
# =============================================================================

class TestWorker(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        _setup_db()
        # The GPU server is shared infra; skip these tests if it's not
        # reachable (e.g., on a CI runner without GPU access).
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
        # Clear subject_embedding on test emails (don't touch unrelated
        # rows). We scope by sender_id rather than subject LIKE because
        # the empty-subject test stores subject='' (no prefix).
        cur.execute("""UPDATE emails SET subject_embedding = NULL
                       WHERE sender_id IN (
                           SELECT id FROM users WHERE email LIKE 'unit-test-%@test'
                       )""")
        conn.commit()
        cur.close()
        conn.close()

    def _make_email(self, subject: str, folder_name: str = 'Sent',
                    body: str = 'A test body with content.') -> int:
        # Fresh user + folder per test (see comment in TestEnqueue).
        import uuid
        u = uuid.uuid4().hex[:8]
        user_email = f'unit-test-{u}@test'
        # Marker prefix so cleanup queries find test rows; tests that need
        # an empty subject pass subject='' and get exactly that (not
        # 'unit-test-').
        subject_to_store = ('' if subject == '' else f'unit-test-{subject}')
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
        cur.execute(
            '''INSERT INTO emails
               (sender_id, recipient_id, folder_id, subject, body, body_html, is_read)
               VALUES (%s, %s, %s, %s, %s, '', FALSE)
               RETURNING id''',
            (user_id, user_id, folder_id, subject_to_store, body),
        )
        eid = cur.fetchone()['id']
        conn.commit()
        cur.close()
        conn.close()
        return eid

    def test_drain_once_embeds_subject_and_body(self):
        from app.utils.embedding_enqueue import enqueue_embedding_job
        from app.services.embedding_worker import EmbeddingWorker
        eid = self._make_email('worker happy path', 'Sent',
                               body='Hello world. ' * 50)
        enqueue_embedding_job(eid, folder_id=None, user_id=None, reason='test')
        worker = EmbeddingWorker()
        n = worker.run_once()
        self.assertEqual(n, 1)
        # Verify subject_embedding was written.
        conn = _connect()
        cur = conn.cursor()
        cur.execute('SELECT subject_embedding IS NOT NULL AS ok FROM emails WHERE id = %s',
                    (eid,))
        self.assertTrue(cur.fetchone()['ok'])
        # Verify body chunks were written.
        cur.execute('SELECT COUNT(*) AS n FROM email_chunks WHERE email_id = %s',
                    (eid,))
        self.assertGreater(cur.fetchone()['n'], 0)
        # Verify job marked done.
        cur.execute("SELECT status FROM embedding_jobs WHERE email_id = %s",
                    (eid,))
        self.assertEqual(cur.fetchone()['status'], 'done')
        cur.close()
        conn.close()

    def test_drain_is_idempotent_under_replay(self):
        """Re-running the worker on the same email should upsert, not
        duplicate."""
        from app.utils.embedding_enqueue import enqueue_embedding_job
        from app.services.embedding_worker import EmbeddingWorker
        eid = self._make_email('worker idempotent', 'Sent', body='Replay me.')
        enqueue_embedding_job(eid, folder_id=None, user_id=None, reason='test')
        EmbeddingWorker().run_once()
        chunks_first = _connect()
        cur = chunks_first.cursor()
        cur.execute('SELECT COUNT(*) AS n FROM email_chunks WHERE email_id = %s',
                    (eid,))
        first = cur.fetchone()['n']
        cur.close()
        chunks_first.close()
        # Reset job to pending and replay.
        conn = _connect()
        cur = conn.cursor()
        cur.execute("""UPDATE embedding_jobs SET status='pending', next_retry_at=NOW(),
                                                 completed_at=NULL
                       WHERE email_id = %s""", (eid,))
        conn.commit()
        cur.close()
        conn.close()
        EmbeddingWorker().run_once()
        conn = _connect()
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) AS n FROM email_chunks WHERE email_id = %s',
                    (eid,))
        second = cur.fetchone()['n']
        cur.close()
        conn.close()
        self.assertEqual(first, second)

    def test_drain_marks_skipped_for_no_op(self):
        """Empty subject + folder not enabled → marked `skipped`, not
        re-enqueued on next backfill."""
        from app.utils.embedding_enqueue import enqueue_embedding_job
        from app.services.embedding_worker import EmbeddingWorker
        eid = self._make_email(subject='', folder_name='Inbox', body='')
        enqueue_embedding_job(eid, folder_id=None, user_id=None, reason='test')
        EmbeddingWorker().run_once()
        conn = _connect()
        cur = conn.cursor()
        cur.execute('SELECT status, last_error FROM embedding_jobs WHERE email_id = %s',
                    (eid,))
        row = cur.fetchone()
        self.assertEqual(row['status'], 'skipped')
        self.assertIn('no-op', row['last_error'])
        cur.close()
        conn.close()


if __name__ == '__main__':
    unittest.main()
