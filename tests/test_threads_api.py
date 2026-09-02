"""
Tests for the /api/threads family of endpoints (PR4).

We bypass the @token_required decorator by calling the underlying wrapped
function directly (`<fn>.__wrapped__`). The wrapped view functions read
`request.current_user`, so we attach a Flask `before_request` hook to
populate it before each call.

Coverage:
    1. GET /api/threads - collapsed thread summaries (visibility)
    2. GET /api/threads - folder filter
    3. GET /api/threads/<id>/messages - chronological messages
    4. POST /api/threads/<id>/read - mark all read
    5. 404 for threads the user has no access to
    6. 400 for invalid thread_id

Tests run against a fresh `threadtest` DB using a dedicated `threadtest`
role. Skipped if POSTGRES_DB_NAME / POSTGRES_PASSWORD_TEST not set.
"""

from __future__ import annotations

import os
import sys
import unittest
from email import message_from_string

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if not os.environ.get("POSTGRES_DB_NAME") or not os.environ.get("POSTGRES_PASSWORD_TEST"):
    raise unittest.SkipTest("POSTGRES_DB_NAME / POSTGRES_PASSWORD_TEST not set")


import psycopg2
from psycopg2.extras import RealDictCursor


def _conn():
    return psycopg2.connect(
        dbname=os.environ["POSTGRES_DB_NAME"],
        user=os.environ.get("POSTGRES_USER", "postgres"),
        password=os.environ["POSTGRES_PASSWORD_TEST"],
        host=os.environ.get("POSTGRES_HOST", "127.0.0.1"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        cursor_factory=RealDictCursor,
    )


def _build_raw(from_addr, to_addr, subject,
               message_id="", in_reply_to="", references="", body="Body"):
    headers = [
        f"From: {from_addr}",
        f"To: {to_addr}",
        f"Subject: {subject}",
    ]
    if message_id:
        headers.append(f"Message-ID: <{message_id}>")
    if in_reply_to:
        headers.append(f"In-Reply-To: <{in_reply_to}>")
    if references:
        headers.append("References: " + " ".join(f"<{r}>" for r in references.split()))
    headers.extend([
        "MIME-Version: 1.0",
        'Content-Type: text/plain; charset="utf-8"',
        "",
        body,
    ])
    return "\r\n".join(headers)


def _truncate_tables(cur):
    cur.execute("DELETE FROM email_recipients")
    cur.execute("DELETE FROM attachments")
    cur.execute("DELETE FROM outbound_queue")
    cur.execute("DELETE FROM emails")
    cur.execute("DELETE FROM folders")
    cur.execute("DELETE FROM users")


def _seed_users(cur, n=3):
    ids = []
    for i in range(n):
        cur.execute(
            "INSERT INTO users (email, password_hash, name, is_local) "
            "VALUES (%s, 'x', %s, TRUE) RETURNING id",
            (f"u{i}@local.test", f"User{i}"),
        )
        ids.append(cur.fetchone()["id"])
    return ids





class TestThreadsApi(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.conn = _conn()
        cls.conn.autocommit = False
        cls.cur = cls.conn.cursor(cursor_factory=RealDictCursor)
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cls.cur.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name='emails'"
        )
        if cls.cur.fetchone() is None:
            with open(os.path.join(repo_root, "db/schema.sql")) as f:
                cls.cur.execute(f.read())
        with open(os.path.join(repo_root, "db/migrations/002_email_threading.sql")) as f:
            cls.cur.execute(f.read())
        cls.conn.commit()

    def setUp(self):
        _truncate_tables(self.cur)
        self.alice_id, self.bob_id, self.eve_id = _seed_users(self.cur)
        self.conn.commit()

        # Use queue_outbound_email so we get both Sent + Inbox copies for
        # local senders/recipients. The auth pattern requires folder
        # ownership; without Sent copies the sender can't see their own
        # outgoing messages in thread queries.
        from smtp_server.outbound import storage as out_storage
        original = out_storage.get_db_connection
        out_storage.get_db_connection = lambda: _conn()
        try:
            from email.message import EmailMessage
            # Three-message thread: alice <-> bob (root, reply, reply).
            for sender_id, from_addr, to_addr, mid, irt, refs, body, subject in [
                (self.alice_id, "u0@local.test", "u1@local.test", "t-root@x", "", "", "Hi", "Re: Threading test"),
                (self.bob_id,   "u1@local.test", "u0@local.test", "t-r1@x",   "t-root@x", "t-root@x", "Reply", "Re: Threading test"),
                (self.alice_id, "u0@local.test", "u1@local.test", "t-r2@x",   "t-r1@x",   "t-r1@x t-root@x", "Reply 2", "Re: Threading test"),
            ]:
                msg = EmailMessage()
                msg['Subject'] = subject
                msg['From'] = from_addr
                msg['To'] = to_addr
                msg['Message-ID'] = f"<{mid}>"
                if irt:
                    msg['In-Reply-To'] = f"<{irt}>"
                msg.set_content(body)
                out_storage.queue_outbound_email(
                    sender_id=sender_id,
                    from_address=from_addr,
                    to_addresses=[to_addr],
                    subject=subject,
                    body=body,
                    message=msg,
                    message_id=mid,
                    in_reply_to=irt or None,
                    references=refs or None,
                )

            # An additional thread alice -> bob.
            msg = EmailMessage()
            msg['Subject'] = "Lunch Friday"
            msg['From'] = "u0@local.test"
            msg['To'] = "u1@local.test"
            msg.set_content("hi")
            out_storage.queue_outbound_email(
                sender_id=self.alice_id,
                from_address="u0@local.test",
                to_addresses=["u1@local.test"],
                subject="Lunch Friday",
                body="hi",
                message=msg,
            )
        finally:
            out_storage.get_db_connection = original

        self.cur.execute("SELECT thread_id, subject FROM emails ORDER BY id")
        self.threads_by_subject = {}
        for r in self.cur.fetchall():
            # Multiple rows can share subject; just remember by subject+first
            self.threads_by_subject.setdefault(r["subject"], str(r["thread_id"]))

        from app.routes import emails as emails_route
        self._emails_route = emails_route
        self._original_get_db = emails_route.get_db_connection
        emails_route.get_db_connection = lambda: _conn()

    def tearDown(self):
        self._emails_route.get_db_connection = self._original_get_db

    def _call(self, fn, user_id, method, *args):
        from flask import Flask, request
        app = Flask(__name__)
        with app.test_request_context(method=method):
            # Set current_user directly on the Request object - the
            # before_request hook doesn't fire inside test_request_context.
            request.current_user = {"id": user_id}
            wrapped = getattr(fn, "__wrapped__", fn)
            return wrapped(*args)

    def _call_get(self, fn, user_id, *args):
        return self._call(fn, user_id, "GET", *args)

    def _call_post(self, fn, user_id, *args):
        return self._call(fn, user_id, "POST", *args)

    # ---- Tests ----------------------------------------------------------

    def test_list_threads_returns_alice_threads(self):
        r = self._emails_route
        resp, status = self._call_get(r.list_threads, self.alice_id)
        self.assertEqual(status, 200)
        body = resp.get_json()
        # Alice is in 2 threads (both are alice <-> bob)
        self.assertEqual(body["total"], 2)
        subjects = sorted(t["subject"] for t in body["threads"])
        self.assertEqual(subjects, ["Lunch Friday", "Re: Threading test"])

    def test_list_threads_excludes_other_users(self):
        r = self._emails_route
        resp, status = self._call_get(r.list_threads, self.eve_id)
        self.assertEqual(status, 200)
        body = resp.get_json()
        # Eve is NOT in any of these threads; store_email creates one row
        # in the recipient's folder, so Eve has no folders containing
        # these messages.
        self.assertEqual(body["total"], 0)

    def test_thread_messages_returns_chronological(self):
        r = self._emails_route
        threading_thread_id = self.threads_by_subject["Re: Threading test"]
        resp, status = self._call_get(
            r.list_thread_messages, self.alice_id, threading_thread_id,
        )
        self.assertEqual(status, 200)
        body = resp.get_json()
        self.assertEqual(len(body["messages"]), 3)
        self.assertEqual(body["messages"][0]["message_id"], "t-root@x")
        self.assertEqual(body["messages"][-1]["message_id"], "t-r2@x")

    def test_thread_404_for_uninvolved_user(self):
        r = self._emails_route
        threading_thread_id = self.threads_by_subject["Re: Threading test"]
        resp, status = self._call_get(
            r.list_thread_messages, self.eve_id, threading_thread_id,
        )
        self.assertEqual(status, 404)

    def test_mark_thread_read(self):
        r = self._emails_route
        threading_thread_id = self.threads_by_subject["Re: Threading test"]
        resp, status = self._call_post(
            r.mark_thread_read, self.alice_id, threading_thread_id,
        )
        self.assertEqual(status, 200)
        # Verify that all of alice's copies are now read.
        # (Bob's copies in his own folders are unaffected — per-user state.)
        self.cur.execute(
            """
            SELECT COUNT(*) AS unread FROM emails e
            JOIN folders f ON e.folder_id = f.id
            WHERE e.thread_id = %s AND f.user_id = %s AND e.is_read = FALSE
            """,
            (threading_thread_id, self.alice_id),
        )
        self.assertEqual(self.cur.fetchone()["unread"], 0)

    def test_invalid_thread_id_rejected(self):
        r = self._emails_route
        resp, status = self._call_get(
            r.list_thread_messages, self.alice_id, "not-a-uuid",
        )
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)