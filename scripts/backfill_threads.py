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
import sys
import uuid
from collections import defaultdict
from typing import Optional

import psycopg2
from psycopg2.extras import RealDictCursor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the parsing helpers from the canonical location. PR2 lifted them
# here from the script so live capture paths (PR3) and the backfill (this
# script) share one implementation.
from app.utils.emails import (
    MAX_CHAIN_DEPTH,  # noqa: F401 — re-exported for back-compat with PR1 tests
    compute_thread_id,
    extract_from_headers_blob,
    extract_threading_headers,
    normalize_subject,
)

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
# Helpers (parsing + thread-ID) live in app.utils.emails; imported above.
# =============================================================================


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

            if refs or irt or subj_norm:
                tid, strategy = compute_thread_id(
                    cursor,
                    message_id=mid,
                    in_reply_to=irt,
                    references_chain=refs,
                    candidate_root_id=email_id,
                    subject_normalized=subj_norm,
                )
                if tid:
                    counts[strategy] = counts.get(strategy, 0) + 1
                else:
                    # compute_thread_id returned (None, reason); count as
                    # no_signal and fall through to the lone-message UUID.
                    counts["no_signal"] += 1
                    tid = str(uuid.uuid4())
                    strategy = "lone_message"
                    counts[strategy] = counts.get(strategy, 0) + 1
            else:
                counts["no_signal"] += 1
                tid = str(uuid.uuid4())
                strategy = "lone_message"
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