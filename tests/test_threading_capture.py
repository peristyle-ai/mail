"""
Tests for threading capture at insertion paths (PR3).

Four paths to validate:
    1. smtp_server.email_storage.store_email (SMTP DATA inbound)
    2. app.routes.inbound.receive_inbound_webhook (POST /inbound)
    3. smtp_server.outbound.storage.queue_outbound_email (local delivery -
       Sent + N Inbox copies share message_id + thread_id)
    4. queue_outbound_email threading fields round-trip (in_reply_to +
       References + client-supplied message_id all reach the DB unchanged)

Tests run against a fresh `threadtest` DB using a dedicated `threadtest`
role - NOT the `postgres` superuser (the 2026-09-02 incident taught us
that lesson). Skipped if POSTGRES_DB_NAME / POSTGRES_PASSWORD_TEST not set.

Run:
    POSTGRES_DB_NAME=threadtest POSTGRES_USER=threadtest \
    POSTGRES_PASSWORD_TEST=threadtest_pw \
    python3 tests/test_threading_capture.py
"""

from __future__ import annotations

import os
import sys
import unittest
from email import message_from_string
from email.message import EmailMessage
from typing import Optional

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


def _build_raw(from_addr: str, to_addr: str, subject: str,
               message_id: str = "", in_reply_to: str = "",
               references: str = "", body: str = "Body") -> str:
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


def _seed_users(cur, sender_local: bool = True, recipient_local: bool = True):
    """Create sender/recipient users; returns (sender_id, recipient_id)."""
    cur.execute(
        "INSERT INTO users (email, password_hash, name, is_local) "
        "VALUES (%s, 'x', 'Sender', %s) RETURNING id",
        ("sender@local.test", sender_local),
    )
    sender_id = cur.fetchone()["id"]
    cur.execute(
        "INSERT INTO users (email, password_hash, name, is_local) "
        "VALUES (%s, 'x', 'Recipient', %s) RETURNING id",
        ("recipient@local.test", recipient_local),
    )
    recipient_id = cur.fetchone()["id"]
    return sender_id, recipient_id


# =============================================================================
# Path 1: SMTP DATA inbound (smtp_server.email_storage.store_email)
# =============================================================================

class TestSmtpInboundCapture(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.conn = _conn()
        cls.conn.autocommit = False
        cls.cur = cls.conn.cursor(cursor_factory=RealDictCursor)
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # Only apply schema.sql if emails table doesn't exist (it's not
        # idempotent - no IF NOT EXISTS guards). Migration IS idempotent.
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
        self.sender_id, self.recipient_id = _seed_users(self.cur)
        self.conn.commit()

    def test_full_headers_populate_thread_fields(self):
        from smtp_server import email_storage as es
        original = es.get_db_connection
        es.get_db_connection = lambda: _conn()
        try:
            raw = _build_raw(
                "sender@local.test", "recipient@local.test",
                "Re: Lunch", "smtp-1@x", in_reply_to="smtp-root@x",
                references="smtp-root@x",
            )
            msg = message_from_string(raw)
            es.store_email("sender@local.test", "recipient@local.test",
                           msg, raw.encode())
        finally:
            es.get_db_connection = original

        self.cur.execute(
            "SELECT message_id, in_reply_to, references_chain, thread_id "
            "FROM emails"
        )
        row = self.cur.fetchone()
        self.assertEqual(row["message_id"], "smtp-1@x")
        self.assertEqual(row["in_reply_to"], "smtp-root@x")
        self.assertEqual(row["references_chain"], "smtp-root@x")
        self.assertIsNotNone(row["thread_id"])

    def test_no_headers_still_gets_thread_id(self):
        from smtp_server import email_storage as es
        original = es.get_db_connection
        es.get_db_connection = lambda: _conn()
        try:
            raw = _build_raw(
                "sender@local.test", "recipient@local.test", "Hello",
            )
            msg = message_from_string(raw)
            es.store_email("sender@local.test", "recipient@local.test",
                           msg, raw.encode())
        finally:
            es.get_db_connection = original

        self.cur.execute("SELECT message_id, thread_id FROM emails")
        row = self.cur.fetchone()
        # No Message-ID supplied, so the column is NULL but thread_id is set
        # (lone_message fallback).
        self.assertIsNone(row["message_id"])
        self.assertIsNotNone(row["thread_id"])


# =============================================================================
# Path 2: Webhook inbound (app.routes.inbound.receive_inbound_webhook)
# =============================================================================

class TestWebhookInboundCapture(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.conn = _conn()
        cls.conn.autocommit = False
        cls.cur = cls.conn.cursor(cursor_factory=RealDictCursor)
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # Only apply schema.sql if emails table doesn't exist (it's not
        # idempotent - no IF NOT EXISTS guards). Migration IS idempotent.
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
        self.sender_id, self.recipient_id = _seed_users(self.cur)
        self.conn.commit()

    def test_webhook_extracts_thread_from_raw_mime(self):
        from app.routes import inbound as inb
        original = inb.get_db_connection
        inb.get_db_connection = lambda: _conn()
        try:
            raw = _build_raw(
                "sender@local.test", "recipient@local.test",
                "Re: Hooks", "hook-1@x", references="hook-root@x",
            )
            payload = {
                "from": "sender@local.test",
                "to": "recipient@local.test",
                "subject": "Re: Hooks",
                "raw_email": raw,
            }
            from flask import Flask
            app = Flask(__name__)
            # Stub the inbound verification function (the route calls this,
            # not verify_webhook_secret directly).
            original_verify = inb._verify_inbound_request
            inb._verify_inbound_request = lambda *a, **kw: (True, "")
            try:
                with app.test_request_context(json=payload, method="POST"):
                    resp = inb.receive_inbound_webhook()
            finally:
                inb._verify_inbound_request = original_verify
        finally:
            inb.get_db_connection = original

        self.cur.execute(
            "SELECT message_id, references_chain, thread_id FROM emails"
        )
        row = self.cur.fetchone()
        self.assertIsNotNone(row, "no row inserted by webhook")
        self.assertEqual(row["message_id"], "hook-1@x")
        self.assertEqual(row["references_chain"], "hook-root@x")
        self.assertIsNotNone(row["thread_id"])


# =============================================================================
# Path 3: queue_outbound_email - local delivery shares message_id+thread_id
# =============================================================================

class TestOutboundLocalDelivery(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.conn = _conn()
        cls.conn.autocommit = False
        cls.cur = cls.conn.cursor(cursor_factory=RealDictCursor)
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # Only apply schema.sql if emails table doesn't exist (it's not
        # idempotent - no IF NOT EXISTS guards). Migration IS idempotent.
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
        self.sender_id, self.recipient_id = _seed_users(self.cur)
        self.conn.commit()

    def _queue_local(self, from_user_id, from_addr, to_addrs, body="hi"):
        from smtp_server.outbound import storage as out_storage
        msg = EmailMessage()
        msg['Subject'] = f"Test {from_addr}"
        msg['From'] = from_addr
        msg['To'] = ", ".join(to_addrs)
        msg.set_content(body)
        return out_storage.queue_outbound_email(
            sender_id=from_user_id,
            from_address=from_addr,
            to_addresses=to_addrs,
            subject=msg['Subject'],
            body=body,
            message=msg,
        )

    def test_local_delivery_shares_message_id_and_thread_id(self):
        from smtp_server.outbound import storage as out_storage
        original = out_storage.get_db_connection
        out_storage.get_db_connection = lambda: _conn()
        try:
            self._queue_local(self.sender_id, "sender@local.test",
                              ["recipient@local.test"])
        finally:
            out_storage.get_db_connection = original

        self.cur.execute(
            "SELECT id, folder_id, message_id, thread_id "
            "FROM emails ORDER BY id"
        )
        rows = self.cur.fetchall()
        self.assertEqual(len(rows), 2, "expected Sent + Inbox copy")
        sent, inbox = rows
        self.assertEqual(sent["message_id"], inbox["message_id"])
        self.assertEqual(str(sent["thread_id"]), str(inbox["thread_id"]))
        self.assertNotEqual(sent["folder_id"], inbox["folder_id"])
        # Message-ID should be auto-generated (UUID@domain)
        self.assertTrue(sent["message_id"].endswith("@local.test"))

    def test_in_reply_to_round_trip(self):
        from smtp_server.outbound import storage as out_storage
        original = out_storage.get_db_connection
        out_storage.get_db_connection = lambda: _conn()
        try:
            # Send a "parent" first
            parent_id, _ = self._queue_local(
                self.sender_id, "sender@local.test",
                ["recipient@local.test"], body="parent",
            )
            self.cur.execute(
                "SELECT message_id, thread_id FROM emails WHERE id = %s",
                (parent_id,),
            )
            parent = self.cur.fetchone()
            parent_mid = parent["message_id"]
            parent_tid = str(parent["thread_id"])

            # Reply from recipient with in_reply_to pointing at parent
            reply_msg = EmailMessage()
            reply_msg['Subject'] = "Re: Test"
            reply_msg['From'] = "recipient@local.test"
            reply_msg['To'] = "sender@local.test"
            reply_msg['In-Reply-To'] = f"<{parent_mid}>"
            reply_msg.set_content("reply body")
            reply_id, _ = out_storage.queue_outbound_email(
                sender_id=self.recipient_id,
                from_address="recipient@local.test",
                to_addresses=["sender@local.test"],
                subject="Re: Test",
                body="reply body",
                message=reply_msg,
                in_reply_to=parent_mid,
            )
        finally:
            out_storage.get_db_connection = original

        self.cur.execute(
            "SELECT message_id, in_reply_to, thread_id FROM emails WHERE id = %s",
            (reply_id,),
        )
        reply = self.cur.fetchone()
        self.assertEqual(reply["in_reply_to"], parent_mid)
        self.assertEqual(str(reply["thread_id"]), parent_tid)

    def test_caller_supplied_message_id_used(self):
        from smtp_server.outbound import storage as out_storage
        original = out_storage.get_db_connection
        out_storage.get_db_connection = lambda: _conn()
        try:
            msg = EmailMessage()
            msg['Subject'] = "Supplied MID"
            msg['From'] = "sender@local.test"
            msg['To'] = "recipient@local.test"
            msg.set_content("x")
            sent_id, _ = out_storage.queue_outbound_email(
                sender_id=self.sender_id,
                from_address="sender@local.test",
                to_addresses=["recipient@local.test"],
                subject="Supplied MID",
                body="x",
                message=msg,
                message_id="custom-mid@example.com",
            )
        finally:
            out_storage.get_db_connection = original

        self.cur.execute(
            "SELECT message_id FROM emails WHERE id = %s", (sent_id,),
        )
        row = self.cur.fetchone()
        self.assertEqual(row["message_id"], "custom-mid@example.com")


if __name__ == "__main__":
    unittest.main(verbosity=2)