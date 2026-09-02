#!/usr/bin/env python3
"""
Backfill thread_id / message_id / in_reply_to / references for existing emails.

This is the one-shot backfill half of PR1 for email threading support (see
coding_agent/plan_threading.md). It scans every email row, extracts RFC 2822
threading headers from `raw_email` (preferred) or `headers` (fallback), and
threads them using the same algorithm used at insert-time (so newly-captured
emails and backfilled ones join the same thread):

    1. References chain    -> root is the first Message-ID in References
    2. In-Reply-To walk    -> walk `message_id = in_reply_to` to the root
    3. Subject fallback    -> normalized subject + sorted participant IDs

The script is:
    * idempotent   - by default only fills NULL columns (safe to re-run)
    * batched      - commits every `--batch-size` rows (default 500)
    * non-destructive - only writes the four new columns; never touches body,
                        subject, recipients, etc.

Usage:
    # Inspect current state (no writes)
    python scripts/backfill_threads.py --status

    # Dry run on the first 50 rows
    python scripts/backfill_threads.py --dry-run --limit 50

    # Run the full backfill
    python scripts/backfill_threads.py

    # Force re-stitch every row (e.g. after a logic fix)
    python scripts/backfill_threads.py --rebuild --batch-size 1000
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import uuid
from collections import defaultdict
from email import message_from_string
from email.message import Message
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# This script intentionally does NOT import from `app.db` (which transitively
# imports Flask, flasgger, the whole app stack). The backfill is an
# operator-run, one-shot tool; using psycopg2 directly makes it runnable on
# any host with the right DATABASE_URL set, regardless of whether the Flask
# stack is installed.


def _get_db_connection():
    """Open a RealDictCursor Postgres connection from DATABASE_URL."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL env var is required", file=sys.stderr)
        sys.exit(2)
    return psycopg2.connect(url, cursor_factory=RealDictCursor)


# =============================================================================
# Parsing helpers (PR2 will lift these into app/utils/emails.py)
# =============================================================================

_RE_PREFIX = re.compile(r"^\s*(re|fwd|fw)\s*:\s*", re.IGNORECASE)


def normalize_subject(subject: Optional[str]) -> str:
    """Strip leading Re:/Fwd:/Fw: prefixes (case-insensitive, repeated) and
    lower-case the result. Returns '' for empty/None input."""
    if not subject:
        return ""
    s = subject.strip()
    while True:
        new = _RE_PREFIX.sub("", s, count=1)
        if new == s:
            break
        s = new
    return s.lower()


def _strip_brackets(msg_id: str) -> str:
    """Strip surrounding angle brackets and whitespace; tolerate missing brackets."""
    s = msg_id.strip()
    if s.startswith("<") and s.endswith(">"):
        s = s[1:-1].strip()
    return s


def extract_threading_headers(raw_text: Optional[str]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Parse Message-ID / In-Reply-To / References from a raw RFC 2822 message.

    Returns (message_id, in_reply_to, references) - all without angle brackets.
    Any missing header is None.
    """
    if not raw_text:
        return None, None, None
    try:
        msg = message_from_string(raw_text)
    except Exception:
        return None, None, None

    mid = _strip_brackets(msg.get("Message-ID", "") or "")
    irt = _strip_brackets(msg.get("In-Reply-To", "") or "")

    refs_raw = (msg.get("References", "") or "").strip()
    if refs_raw:
        # References is a space-separated list of Message-IDs, each optionally
        # surrounded by angle brackets.
        parts = [_strip_brackets(p) for p in refs_raw.split()]
        refs = " ".join(p for p in parts if p)
    else:
        refs = ""

    return (mid or None, irt or None, refs or None)


def extract_from_headers_blob(headers_blob: Optional[str]) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Fallback parser for the `headers` column (newline-separated "K: V" pairs).
    Less reliable than parsing raw_email but covers rows where raw_email was
    not stored."""
    if not headers_blob:
        return None, None, None
    mid = irt = refs = None
    for line in headers_blob.splitlines():
        if line.startswith((" ", "\t")):
            continue  # folded continuation
        if ":" not in line:
            continue
        name, _, value = line.partition(":")
        name_lc = name.strip().lower()
        value = value.strip()
        if name_lc == "message-id" and not mid:
            mid = _strip_brackets(value)
        elif name_lc == "in-reply-to" and not irt:
            irt = _strip_brackets(value)
        elif name_lc == "references" and not refs:
            parts = [_strip_brackets(p) for p in value.split()]
            refs = " ".join(p for p in parts if p)
    return (mid or None, irt or None, refs or None)


# =============================================================================
# Thread-stitching logic (PR2 will move this too; the SQL lives here for now
# because it's only used by the backfill today)
# =============================================================================

MAX_CHAIN_DEPTH = 50  # guard against References / In-Reply-To cycles


def resolve_thread_id_by_references(
    cursor, refs: str, candidate_root_id: Optional[int]
) -> tuple[Optional[str], str]:
    """Given a space-separated References chain, return (thread_id, reason).

    Strategy:
        1. If any Message-ID in the chain belongs to an existing email row,
           use that row's thread_id (or assign a fresh one if it's NULL).
        2. Otherwise return None with reason='no_chain_match'.

    `candidate_root_id` is the email we're processing; if its own Message-ID
    happens to be in its own chain (defensive), we still treat it as a new
    thread root.
    """
    if not refs:
        return None, "no_refs"

    ids = [r for r in refs.split() if r]
    for mid in ids:
        cursor.execute(
            "SELECT id, thread_id FROM emails WHERE message_id = %s LIMIT 1",
            (mid,),
        )
        row = cursor.fetchone()
        if row and row["id"] != candidate_root_id:
            if row["thread_id"]:
                return row["thread_id"], "references"
            # Found the parent but it has no thread_id yet - hand back its id
            # so the caller can stitch. (We do the actual UPDATE here.)
            new_tid = str(uuid.uuid4())
            cursor.execute(
                "UPDATE emails SET thread_id = %s WHERE id = %s AND thread_id IS NULL",
                (new_tid, row["id"]),
            )
            return new_tid, "references"

    return None, "no_chain_match"


def resolve_thread_id_by_in_reply_to(cursor, irt: str, candidate_root_id: Optional[int]) -> tuple[Optional[str], str]:
    """Walk `message_id = in_reply_to` recursively until we hit a row with no
    parent. Return that ancestor's thread_id (or a fresh UUID we just minted
    for it)."""
    if not irt:
        return None, "no_irt"

    current_mid = irt
    visited = set()
    for _ in range(MAX_CHAIN_DEPTH):
        if current_mid in visited:
            return None, "cycle"
        visited.add(current_mid)

        cursor.execute(
            """
            SELECT e.id, e.thread_id, e.in_reply_to
              FROM emails e
             WHERE e.message_id = %s
             ORDER BY e.id ASC
             LIMIT 1
            """,
            (current_mid,),
        )
        row = cursor.fetchone()
        if not row:
            return None, "irt_not_found"
        if row["id"] == candidate_root_id:
            # Don't follow a cycle back to ourselves.
            return None, "self_parent"
        if row["thread_id"]:
            return row["thread_id"], "in_reply_to"
        if not row["in_reply_to"]:
            # Root of the chain - mint a new UUID and stamp it.
            new_tid = str(uuid.uuid4())
            cursor.execute(
                "UPDATE emails SET thread_id = %s WHERE id = %s AND thread_id IS NULL",
                (new_tid, row["id"]),
            )
            return new_tid, "in_reply_to"
        current_mid = row["in_reply_to"]

    return None, "depth_exceeded"


def participants_key(cursor, email_id: int) -> Optional[frozenset]:
    """Return a stable set of (sender_id, *recipient_user_ids) for an email.
    None if sender is missing (shouldn't happen, but be defensive)."""
    cursor.execute("SELECT sender_id FROM emails WHERE id = %s", (email_id,))
    row = cursor.fetchone()
    if not row or row["sender_id"] is None:
        return None
    sender_id = row["sender_id"]
    cursor.execute(
        "SELECT user_id FROM email_recipients WHERE email_id = %s",
        (email_id,),
    )
    recipients = {r["user_id"] for r in cursor.fetchall()}
    return frozenset({sender_id, *recipients})


# =============================================================================
# Main backfill routine
# =============================================================================

def status(cursor) -> dict:
    """Print current threading column population. No writes."""
    cursor.execute(
        """
        SELECT
            COUNT(*)                                                     AS total,
            COUNT(*) FILTER (WHERE thread_id IS NOT NULL)                 AS with_thread_id,
            COUNT(*) FILTER (WHERE message_id IS NOT NULL)                AS with_message_id,
            COUNT(*) FILTER (WHERE in_reply_to IS NOT NULL)               AS with_in_reply_to,
            COUNT(*) FILTER (WHERE references_chain IS NOT NULL)         AS with_references_chain,
            COUNT(*) FILTER (WHERE subject_normalized IS NOT NULL)        AS with_subject_normalized,
            COUNT(*) FILTER (WHERE raw_email IS NOT NULL AND raw_email != '') AS with_raw_email,
            COUNT(*) FILTER (WHERE (headers IS NOT NULL AND headers != '')
                              AND (raw_email IS NULL OR raw_email = ''))  AS headers_only
        FROM emails
        """
    )
    row = cursor.fetchone()
    print("Threading backfill status:")
    for k, v in row.items():
        print(f"  {k:30s} {v}")
    return row


def backfill(
    dry_run: bool = False,
    limit: Optional[int] = None,
    batch_size: int = 500,
    rebuild: bool = False,
) -> dict:
    """Run the backfill. Returns a counts dict (strategy -> row count)."""
    conn = _get_db_connection()
    cursor = conn.cursor()

    print(f"Backfill starting (dry_run={dry_run}, limit={limit}, "
          f"batch_size={batch_size}, rebuild={rebuild})")

    # Select rows to process.
    where = "1=1" if rebuild else "thread_id IS NULL"
    sql = f"""
        SELECT id, subject, raw_email, headers
          FROM emails
         WHERE {where}
         ORDER BY id ASC
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    cursor.execute(sql)
    rows = cursor.fetchall()
    total = len(rows)
    print(f"Selected {total} rows to process")

    counts: dict[str, int] = defaultdict(int)
    errors = 0
    processed = 0

    for row in rows:
        email_id = row["id"]
        subject = row["subject"]
        raw_email = row["raw_email"]
        headers_blob = row["headers"]

        try:
            # 1. Parse headers (raw_email wins; headers blob is fallback)
            mid, irt, refs = extract_threading_headers(raw_email)
            if not (mid or irt or refs):
                mid, irt, refs = extract_from_headers_blob(headers_blob)

            subj_norm = normalize_subject(subject) if subject else ""

            # 2. Resolve thread_id with priority: refs > in_reply_to > subject
            tid = None
            strategy = None

            if refs:
                tid, strategy = resolve_thread_id_by_references(cursor, refs, candidate_root_id=email_id)
                if tid:
                    counts["references"] += 1
            if not tid and irt:
                tid, strategy = resolve_thread_id_by_in_reply_to(cursor, irt, candidate_root_id=email_id)
                if tid:
                    counts["in_reply_to"] += 1
            if not tid:
                # Subject fallback bucket - only when we have at least a
                # normalized subject to key on AND all participants exist.
                pk = participants_key(cursor, email_id)
                if subj_norm and pk:
                    tid = uuid.uuid5(
                        uuid.NAMESPACE_DNS,
                        f"py_pg_email|subject|{subj_norm}|{','.join(str(x) for x in sorted(pk))}",
                    )
                    strategy = "subject_fallback"
                    counts["subject_fallback"] += 1
                else:
                    counts["no_signal"] += 1

            if not tid:
                # Last resort: a per-row fresh UUID so every row ends up with
                # *some* thread_id. This makes future re-stitches possible
                # (a row can never be orphaned by a NULL thread_id), and the
                # API contract is satisfied.
                tid = uuid.uuid4()
                strategy = strategy or "lone_message"
                counts[strategy] = counts.get(strategy, 0) + 1

            # 3. Write the four new columns (plus subject_normalized when we
            # used the subject fallback).
            update_subj_norm = subj_norm if strategy == "subject_fallback" else None
            if not dry_run:
                cursor.execute(
                    """
                    UPDATE emails
                       SET message_id         = %s,
                           in_reply_to        = %s,
                           references_chain   = %s,
                           thread_id          = %s,
                           subject_normalized = COALESCE(%s, subject_normalized)
                     WHERE id = %s
                    """,
                    (mid, irt, refs, str(tid), update_subj_norm, email_id),
                )

            processed += 1

            # Batch commit
            if not dry_run and processed % batch_size == 0:
                conn.commit()
                print(f"  committed batch, processed={processed}/{total}")

        except Exception as e:
            errors += 1
            print(f"  ERROR on email id={email_id}: {e}", file=sys.stderr)
            conn.rollback()

    if not dry_run:
        conn.commit()
    cursor.close()
    conn.close()

    print("\nBackfill summary:")
    for k in ("references", "in_reply_to", "subject_fallback", "lone_message",
              "no_signal", "no_refs", "no_irt", "no_chain_match",
              "irt_not_found", "depth_exceeded", "cycle", "self_parent"):
        if k in counts and counts[k]:
            print(f"  {k:20s} {counts[k]}")
    print(f"  {'processed':20s} {processed}")
    print(f"  {'errors':20s} {errors}")
    if dry_run:
        print("  (dry run - no writes performed)")

    return dict(counts)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--status", action="store_true", help="Show column population and exit")
    parser.add_argument("--dry-run", action="store_true", help="Parse and stage updates but don't write")
    parser.add_argument("--limit", type=int, default=None, help="Maximum rows to process")
    parser.add_argument("--batch-size", type=int, default=500, help="Commit every N rows (default 500)")
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Re-process every row even if thread_id is already set (use after a logic fix)",
    )
    args = parser.parse_args()

    conn = _get_db_connection()
    cursor = conn.cursor()

    if args.status:
        status(cursor)
        cursor.close()
        conn.close()
        return 0

    status(cursor)  # always show status first
    print()

    cursor.close()
    conn.close()

    backfill(
        dry_run=args.dry_run,
        limit=args.limit,
        batch_size=args.batch_size,
        rebuild=args.rebuild,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())