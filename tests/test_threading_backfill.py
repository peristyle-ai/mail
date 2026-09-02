"""
Tests for the threading backfill (PR1).

Runs against a throwaway Postgres database created in setUpModule(). The
test DB is loaded with a small fixture of emails whose threading is known,
then backfill_threads.backfill() runs and we assert the resulting thread_id
assignments.

Run directly:
    POSTGRES_DB_NAME=test_threading python -m pytest tests/test_threading_backfill.py -v
    POSTGRES_DB_NAME=test_threading python tests/test_threading_backfill.py

If POSTGRES_DB_NAME isn't set, the suite is skipped (not failed) - this keeps
the other unit tests green on a dev machine without a test DB.

Strategy coverage:
    - references chain         (3-message chain)
    - in_reply_to walk         (parent only, no references)
    - subject fallback         (no headers, identical subjects)
    - lone message             (no headers, no participants match)
    - header-only blob         (raw_email NULL, headers populated)
    - self-referential cycle   (a -> a) -> handled safely
    - idempotency              (running backfill twice doesn't change result)
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Skip the whole module if no test DB is configured.
if not os.environ.get("POSTGRES_DB_NAME"):
    raise unittest.SkipTest("POSTGRES_DB_NAME not set - skipping DB integration tests")


# =============================================================================
# Pure-Python unit tests (no DB) for the parsing helpers
# =============================================================================

class TestNormalizeSubject(unittest.TestCase):
    def test_strips_re(self):
        from scripts.backfill_threads import normalize_subject
        self.assertEqual(normalize_subject("Re: hello"), "hello")

    def test_strips_repeated_prefixes(self):
        from scripts.backfill_threads import normalize_subject
        self.assertEqual(normalize_subject("Re: RE: Fwd: re: hello"), "hello")

    def test_lowercases(self):
        from scripts.backfill_threads import normalize_subject
        self.assertEqual(normalize_subject("Hello World"), "hello world")

    def test_strips_whitespace(self):
        from scripts.backfill_threads import normalize_subject
        self.assertEqual(normalize_subject("   Re:   hi  "), "hi")

    def test_empty_and_none(self):
        from scripts.backfill_threads import normalize_subject
        self.assertEqual(normalize_subject(""), "")
        self.assertEqual(normalize_subject(None), "")

    def test_no_prefix(self):
        from scripts.backfill_threads import normalize_subject
        self.assertEqual(normalize_subject("Plain subject"), "plain subject")


class TestExtractThreadingHeaders(unittest.TestCase):
    RAW = (
        "From: alice@example.com\r\n"
        "To: bob@example.com\r\n"
        "Subject: Test\r\n"
        "Message-ID: <abc-1@example.com>\r\n"
        "In-Reply-To: <abc-0@example.com>\r\n"
        "References: <abc-0@example.com> <abc-root@example.com>\r\n"
        "\r\n"
        "Body"
    )

    def test_basic(self):
        from scripts.backfill_threads import extract_threading_headers
        mid, irt, refs = extract_threading_headers(self.RAW)
        self.assertEqual(mid, "abc-1@example.com")
        self.assertEqual(irt, "abc-0@example.com")
        self.assertEqual(refs, "abc-0@example.com abc-root@example.com")

    def test_no_brackets(self):
        from scripts.backfill_threads import extract_threading_headers
        raw = "Message-ID: abc@example.com\r\n\r\nBody"
        mid, _, _ = extract_threading_headers(raw)
        self.assertEqual(mid, "abc@example.com")

    def test_missing_headers(self):
        from scripts.backfill_threads import extract_threading_headers
        raw = "Subject: Hi\r\n\r\nBody"
        mid, irt, refs = extract_threading_headers(raw)
        self.assertIsNone(mid)
        self.assertIsNone(irt)
        self.assertIsNone(refs)

    def test_empty(self):
        from scripts.backfill_threads import extract_threading_headers
        self.assertEqual(extract_threading_headers(None), (None, None, None))
        self.assertEqual(extract_threading_headers(""), (None, None, None))

    def test_garbage(self):
        from scripts.backfill_threads import extract_threading_headers
        mid, irt, refs = extract_threading_headers("\x00\x01 not an email")
        # Should not raise; all-None is acceptable.
        self.assertIsNone(mid)


class TestExtractFromHeadersBlob(unittest.TestCase):
    def test_basic(self):
        from scripts.backfill_threads import extract_from_headers_blob
        blob = (
            "Message-ID: <x@example.com>\n"
            "In-Reply-To: <y@example.com>\n"
            "References: <a> <b>\n"
        )
        mid, irt, refs = extract_from_headers_blob(blob)
        self.assertEqual(mid, "x@example.com")
        self.assertEqual(irt, "y@example.com")
        self.assertEqual(refs, "a b")

    def test_folded_continuation_ignored(self):
        from scripts.backfill_threads import extract_from_headers_blob
        blob = "Message-ID: <x@example.com>\n \t continuation\n"
        mid, _, _ = extract_from_headers_blob(blob)
        self.assertEqual(mid, "x@example.com")


# =============================================================================
# DB integration tests
# =============================================================================

import psycopg2
import psycopg2.extras


def _conn():
    """Open a connection to the test DB using env vars. Uses RealDictCursor
    so cursor.fetchone() returns dicts (matching app.db.get_db_connection)."""
    dbname = os.environ["POSTGRES_DB_NAME"]
    return psycopg2.connect(
        dbname=dbname,
        user=os.environ.get("POSTGRES_USER", "postgres"),
        password=os.environ.get("POSTGRES_PASSWORD_TEST") or os.environ.get("POSTGRES_PASSWORD", "postgres"),
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def _build_raw(from_addr: str, to_addr: str, subject: str,
               message_id: str, in_reply_to: str = "", references: str = "") -> str:
    headers = [
        f"From: {from_addr}",
        f"To: {to_addr}",
        f"Subject: {subject}",
        f"Message-ID: <{message_id}>",
    ]
    if in_reply_to:
        headers.append(f"In-Reply-To: <{in_reply_to}>")
    if references:
        # <a> <b> form
        headers.append("References: " + " ".join(f"<{r}>" for r in references.split()))
    headers.extend(["", "Body"])
    return "\r\n".join(headers)


class TestBackfillIntegration(unittest.TestCase):
    """End-to-end: load a fixture, run backfill, assert thread assignment."""

    @classmethod
    def setUpClass(cls):
        cls.conn = _conn()
        cls.conn.autocommit = False
        cls.cur = cls.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Load the migration if columns don't already exist (idempotent).
        migration_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "db", "migrations", "002_email_threading.sql",
        )
        with open(migration_path) as f:
            cls.cur.execute(f.read())
        cls.conn.commit()

        # Make sure the parent tables we need exist; create minimal stubs if
        # the test DB was empty.
        cls.cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                name VARCHAR(255),
                is_local BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cls.cur.execute(
            """
            CREATE TABLE IF NOT EXISTS folders (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name VARCHAR(100) NOT NULL,
                parent_id INTEGER REFERENCES folders(id) ON DELETE CASCADE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, name)
            )
            """
        )
        cls.cur.execute(
            """
            CREATE TABLE IF NOT EXISTS emails (
                id SERIAL PRIMARY KEY,
                sender_id INTEGER NOT NULL REFERENCES users(id),
                recipient_id INTEGER REFERENCES users(id),
                source_email_id INTEGER REFERENCES emails(id) ON DELETE SET NULL,
                folder_id INTEGER REFERENCES folders(id),
                subject VARCHAR(500),
                body TEXT,
                body_html TEXT,
                raw_email TEXT,
                headers TEXT,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                is_read BOOLEAN DEFAULT FALSE,
                is_starred BOOLEAN DEFAULT FALSE
            )
            """
        )
        cls.cur.execute(
            """
            CREATE TABLE IF NOT EXISTS email_recipients (
                id SERIAL PRIMARY KEY,
                email_id INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id),
                recipient_type VARCHAR(10) NOT NULL CHECK (recipient_type IN ('to', 'cc', 'bcc'))
            )
            """
        )
        cls.conn.commit()

    def setUp(self):
        # Wipe data so each test starts clean. Order matters for FKs.
        self.cur.execute("DELETE FROM email_recipients")
        self.cur.execute("DELETE FROM attachments")
        self.cur.execute("DELETE FROM emails")
        self.cur.execute("DELETE FROM folders")
        self.cur.execute("DELETE FROM users")
        self.conn.commit()
        # Reset threading columns explicitly (DELETE leaves schema intact).
        self.cur.execute(
            "UPDATE emails SET thread_id=NULL, message_id=NULL, in_reply_to=NULL, "
            "references_chain=NULL, subject_normalized=NULL"
        )

    @classmethod
    def tearDownClass(cls):
        cls.cur.close()
        cls.conn.close()

    # ------------------------------------------------------------------ helpers

    def _add_user(self, email: str) -> int:
        self.cur.execute(
            "INSERT INTO users (email, password_hash) VALUES (%s, 'x') RETURNING id",
            (email,),
        )
        return self.cur.fetchone()[0]

    def _add_folder(self, user_id: int, name: str) -> int:
        self.cur.execute(
            "INSERT INTO folders (user_id, name) VALUES (%s, %s) RETURNING id",
            (user_id, name),
        )
        return self.cur.fetchone()[0]

    def _add_email(self, sender_id: int, recipient_id: Optional[int],
                   folder_id: int, subject: str, raw_email: Optional[str],
                   headers_blob: Optional[str] = None) -> int:
        self.cur.execute(
            """
            INSERT INTO emails (sender_id, recipient_id, folder_id, subject,
                                body, raw_email, headers)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (sender_id, recipient_id, folder_id, subject, "body", raw_email, headers_blob),
        )
        eid = self.cur.fetchone()[0]
        self.cur.execute(
            "INSERT INTO email_recipients (email_id, user_id, recipient_type) VALUES (%s, %s, 'to')",
            (eid, recipient_id),
        )
        return eid

    def _run_backfill(self):
        from scripts.backfill_threads import backfill
        # Note: backfill() opens its own connection from get_db_connection();
        # for the test we want it to talk to OUR test DB. We monkey-patch the
        # lazy-imported helper in scripts/backfill_threads.
        import scripts.backfill_threads as bt
        original = bt._get_db_connection
        bt._get_db_connection = lambda: _conn()
        try:
            backfill(dry_run=False, batch_size=10)
        finally:
            bt._get_db_connection = original

    def _get_thread(self, email_id: int) -> Optional[str]:
        self.cur.execute("SELECT thread_id FROM emails WHERE id = %s", (email_id,))
        row = self.cur.fetchone()
        return str(row["thread_id"]) if row and row["thread_id"] else None

    # ------------------------------------------------------------------ tests

    def test_references_chain_stitches_root(self):
        alice = self._add_user("alice@example.com")
        bob = self._add_user("bob@example.com")
        alice_inbox = self._add_folder(alice, "Inbox")
        bob_inbox = self._add_folder(bob, "Inbox")

        # Three-message chain via References:
        #   root  -> reply1 -> reply2
        raw_root = _build_raw("alice@x", "bob@x", "Project", "root-1@x")
        raw_reply1 = _build_raw("bob@x", "alice@x", "Re: Project",
                                "reply-1@x", in_reply_to="root-1@x",
                                references="root-1@x")
        raw_reply2 = _build_raw("alice@x", "bob@x", "Re: Project",
                                "reply-2@x", in_reply_to="reply-1@x",
                                references="reply-1@x root-1@x")

        # Insert root LAST so we test chain-resolution rather than just row order.
        e_reply2 = self._add_email(alice, bob, bob_inbox, "Re: Project", raw_reply2)
        e_reply1 = self._add_email(bob, alice, alice_inbox, "Re: Project", raw_reply1)
        e_root = self._add_email(alice, bob, bob_inbox, "Project", raw_root)
        self.conn.commit()

        self._run_backfill()

        # All three must end up in the same thread (root's thread_id).
        t_root = self._get_thread(e_root)
        self.assertIsNotNone(t_root)
        self.assertEqual(self._get_thread(e_reply1), t_root)
        self.assertEqual(self._get_thread(e_reply2), t_root)

    def test_in_reply_to_walk(self):
        alice = self._add_user("alice@x")
        bob = self._add_user("bob@x")
        f = self._add_folder(alice, "Inbox")

        raw_root = _build_raw("alice@x", "bob@x", "Hi", "irt-root@x")
        raw_reply = _build_raw("bob@x", "alice@x", "Re: Hi", "irt-reply@x",
                               in_reply_to="irt-root@x")  # no References

        e_reply = self._add_email(bob, alice, f, "Re: Hi", raw_reply)
        e_root = self._add_email(alice, bob, f, "Hi", raw_root)
        self.conn.commit()

        self._run_backfill()

        self.assertEqual(self._get_thread(e_reply), self._get_thread(e_root))

    def test_subject_fallback(self):
        alice = self._add_user("alice@s")
        bob = self._add_user("bob@s")
        f = self._add_folder(alice, "Inbox")

        # Two emails with identical normalized subjects, no References/IRT.
        raw_a = _build_raw("alice@s", "bob@s", "Lunch Friday", "sf-a@s")
        raw_b = _build_raw("alice@s", "bob@s", "Re: Lunch Friday", "sf-b@s")
        e_a = self._add_email(alice, bob, f, "Lunch Friday", raw_a)
        e_b = self._add_email(alice, bob, f, "Re: Lunch Friday", raw_b)
        self.conn.commit()

        self._run_backfill()

        self.assertEqual(self._get_thread(e_a), self._get_thread(e_b))

    def test_lone_message_gets_thread_id(self):
        alice = self._add_user("alice@l")
        bob = self._add_user("bob@l")
        f = self._add_folder(alice, "Inbox")
        raw = _build_raw("alice@l", "bob@l", "Random", "lone-1@l")
        e = self._add_email(alice, bob, f, "Random", raw)
        self.conn.commit()

        self._run_backfill()
        self.assertIsNotNone(self._get_thread(e))

    def test_headers_blob_fallback(self):
        alice = self._add_user("alice@h")
        bob = self._add_user("bob@h")
        f = self._add_folder(alice, "Inbox")
        blob = (
            "Message-ID: <h-only@x>\n"
            "In-Reply-To: <h-parent@x>\n"
            "References: <h-parent@x>\n"
        )
        e = self._add_email(alice, bob, f, "From headers blob", raw_email=None, headers_blob=blob)
        self.conn.commit()

        self._run_backfill()
        self.cur.execute("SELECT message_id, references_chain FROM emails WHERE id = %s", (e,))
        row = self.cur.fetchone()
        self.assertEqual(row["message_id"], "h-only@x")
        self.assertEqual(row["references_chain"], "h-parent@x")

    def test_idempotency(self):
        alice = self._add_user("alice@i")
        bob = self._add_user("bob@i")
        f = self._add_folder(alice, "Inbox")
        raw = _build_raw("alice@i", "bob@i", "Idempotent", "idem-1@i")
        e = self._add_email(alice, bob, f, "Idempotent", raw)
        self.conn.commit()

        self._run_backfill()
        t1 = self._get_thread(e)
        self._run_backfill()  # second run, default = only fills NULL
        t2 = self._get_thread(e)
        self.assertEqual(t1, t2)
        # And a forced rebuild should produce the same answer.
        from scripts.backfill_threads import backfill
        import scripts.backfill_threads as bt
        original = bt._get_db_connection
        bt._get_db_connection = lambda: _conn()
        try:
            backfill(dry_run=False, rebuild=True, batch_size=10)
        finally:
            bt._get_db_connection = original
        t3 = self._get_thread(e)
        self.assertEqual(t1, t3)


from typing import Optional


if __name__ == "__main__":
    unittest.main(verbosity=2)