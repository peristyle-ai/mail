#!/usr/bin/env python3
"""
Backfill the embedding pipeline for existing emails.

PR1 of the embeddings rollout ships an async worker that catches new mail
on arrival. This script does the same for the historical backlog:

    1. Find every email whose `subject_embedding` is NULL or whose body
       hasn't been chunked yet AND lives in a folder with body embedding
       enabled.
    2. Enqueue a job in `embedding_jobs` per row.
    3. The worker (running separately via systemd) drains them.

The script itself never embeds anything — it just creates rows. Running
the worker is a separate step (it's a long-running service, not a one-
shot).  This separation lets you:
    * inspect the queue first (`--status`)
    * smoke-test a small slice (`--dry-run --limit 10`)
    * enqueue the whole backlog without blocking on the GPU server

Usage:
    # Inspect current state
    python scripts/backfill_embeddings.py --status

    # Preview the first 10 rows (no enqueue)
    python scripts/backfill_embeddings.py --dry-run --limit 10

    # Enqueue everything that needs work
    python scripts/backfill_embeddings.py

    # Only enqueue emails whose subject_embedding is NULL
    python scripts/backfill_embeddings.py --only-subject

    # Only enqueue emails that need body chunking (subject already done)
    python scripts/backfill_embeddings.py --only-body

    # Bypass the per-folder opt-in and force-enqueue every email
    # (use when migrating a fresh folder into the enabled set)
    python scripts/backfill_embeddings.py --force-all

Idempotent — safe to re-run. The enqueue helper skips emails that already
have a live job. Re-running with --only-subject/--only-body after a
partial completion will catch up the missing half.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Iterable, List, Tuple

import psycopg2
from psycopg2.extras import RealDictCursor

# Make `app` importable without forcing the full Flask app to load.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# Use the worker's enqueue helper so policy lives in one place. We import
# the module directly (not via `app`) so we don't drag in the Flask app.
from app.utils import embedding_enqueue
from config import get_config


def _connect():
    url = os.environ.get('DATABASE_URL')
    if not url:
        print('ERROR: DATABASE_URL env var is required', file=sys.stderr)
        sys.exit(2)
    return psycopg2.connect(url, cursor_factory=RealDictCursor)


def status(cursor) -> None:
    """Print a summary of the embedding pipeline state."""
    cursor.execute('SELECT COUNT(*) AS n FROM emails')
    total_emails = cursor.fetchone()['n']
    cursor.execute('SELECT COUNT(*) AS n FROM emails WHERE subject_embedding IS NOT NULL')
    with_subj = cursor.fetchone()['n']
    cursor.execute('SELECT COUNT(*) AS n FROM email_chunks')
    with_chunks = cursor.fetchone()['n']
    cursor.execute('SELECT COUNT(*) AS n FROM embedding_jobs')
    total_jobs = cursor.fetchone()['n']
    cursor.execute("""SELECT status, COUNT(*) AS n FROM embedding_jobs GROUP BY status ORDER BY status""")
    by_status = cursor.fetchall()
    cursor.execute("""SELECT COUNT(DISTINCT email_id) AS n FROM email_chunks""")
    chunked_emails = cursor.fetchone()['n']

    print('=== Embedding pipeline status ===')
    print(f'  emails.total:                {total_emails}')
    print(f'  emails.with subject_embedding: {with_subj} ({with_subj*100/max(total_emails,1):.1f}%)')
    print(f'  email_chunks rows:           {with_chunks}')
    print(f'  emails.with >=1 chunk:       {chunked_emails}')
    print(f'  embedding_jobs.total:        {total_jobs}')
    for row in by_status:
        print(f'    {row["status"]:<10} {row["n"]}')

    enabled = embedding_enqueue._load_enabled_folder_names()
    print(f'  enabled folders (body):      {sorted(enabled) or "(none)"}')

    cursor.execute("""
        SELECT f.name, COUNT(e.id) FILTER (WHERE e.subject_embedding IS NULL) AS missing_subj,
                          COUNT(DISTINCT e.id) FILTER (
                              WHERE NOT EXISTS (
                                  SELECT 1 FROM email_chunks c WHERE c.email_id = e.id
                              )
                          ) AS missing_chunks,
                          COUNT(e.id) AS total
        FROM emails e
        JOIN folders f ON f.id = e.folder_id
        GROUP BY f.name
        ORDER BY total DESC
    """)
    print()
    print('  Per-folder backlog:')
    print(f'    {"folder":<12} {"total":>6} {"miss_subj":>10} {"miss_chunks":>12}')
    for row in cursor.fetchall():
        print(f'    {row["name"]:<12} {row["total"]:>6} {row["missing_subj"]:>10} {row["missing_chunks"]:>12}')


def find_targets(
    cursor,
    *,
    only_subject: bool,
    only_body: bool,
    force_all: bool,
    limit: int | None,
) -> List[int]:
    """Return the email_ids that need embedding work.

    Skip rules:
      * already has pending/processing job            (in flight)
      * already has a `skipped` job for the same op   (the worker has
        already determined there's nothing to do — empty subject +
        folder not enabled). Re-enqueueing would just churn.
      * empty/null subject in --only-subject mode     (nothing to embed)
      * folder not enabled in --only-body mode        (would be skipped)
    """
    where = []
    params: List = []
    if only_subject:
        where.append('e.subject_embedding IS NULL')
        # Don't enqueue emails with empty subjects — worker would mark
        # them `skipped` and we'd re-enqueue on every backfill run.
        where.append('e.subject IS NOT NULL')
        where.append("COALESCE(NULLIF(BTRIM(e.subject), ''), '') <> ''")
    if only_body:
        where.append('NOT EXISTS (SELECT 1 FROM email_chunks c WHERE c.email_id = e.id)')
        # Restrict to enabled folders so we don't enqueue thousands of
        # Inbox / Archive emails the worker would skip.
        enabled = embedding_enqueue._load_enabled_folder_names()
        if enabled:
            placeholders = ','.join(['%s'] * len(enabled))
            params.extend(list(enabled))
            where.append(
                f'EXISTS (SELECT 1 FROM folders f WHERE f.id = e.folder_id '
                f'AND LOWER(f.name) IN ({placeholders}))'
            )
        else:
            # No folders configured — nothing to do for body.
            return []
    if force_all:
        where = ['1=1']

    # Always exclude emails that already have a live (non-terminal) job.
    where.append(
        'NOT EXISTS (SELECT 1 FROM embedding_jobs j '
        'WHERE j.email_id = e.id AND j.status IN (\'pending\',\'processing\'))'
    )
    # Also exclude emails whose latest job was `skipped` for the same op.
    # (We compare by checking that no later non-skipped job exists.)
    where.append(
        '''NOT EXISTS (
            SELECT 1 FROM embedding_jobs j
            WHERE j.email_id = e.id AND j.status = 'skipped'
              AND NOT EXISTS (
                  SELECT 1 FROM embedding_jobs j2
                  WHERE j2.email_id = e.id
                    AND j2.status IN ('done','failed','pending','processing')
                    AND (j2.enqueued_at > j.enqueued_at
                         OR (j2.enqueued_at = j.enqueued_at AND j2.id > j.id))
              )
        )'''
    )

    sql = (
        'SELECT e.id FROM emails e '
        'WHERE ' + ' AND '.join(where) + ' '
        'ORDER BY e.id'
    )
    if limit:
        sql += f' LIMIT {int(limit)}'
    cursor.execute(sql, params)
    return [r['id'] for r in cursor.fetchall()]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split('\n\n', 1)[0])
    p.add_argument('--status', action='store_true', help='Print pipeline status and exit.')
    p.add_argument('--dry-run', action='store_true', help="Don't actually enqueue; just print what would be enqueued.")
    p.add_argument('--limit', type=int, default=None, help='Cap the number of jobs enqueued (useful with --dry-run).')
    p.add_argument('--only-subject', action='store_true', help='Only enqueue emails whose subject_embedding is NULL.')
    p.add_argument('--only-body', action='store_true', help='Only enqueue emails with no chunks (subject already done).')
    p.add_argument('--force-all', action='store_true', help='Enqueue every email regardless of current state.')
    args = p.parse_args()

    cfg = get_config()
    if not cfg.embedding_enabled and not args.status:
        print('embedding.enabled is false in config.yaml; nothing to do.',
              file=sys.stderr)
        return 0

    conn = _connect()
    cursor = conn.cursor()
    try:
        if args.status:
            status(cursor)
            return 0

        targets = find_targets(
            cursor,
            only_subject=args.only_subject,
            only_body=args.only_body,
            force_all=args.force_all,
            limit=args.limit,
        )
        print(f'Candidates: {len(targets)} email(s)')
        if not targets:
            return 0

        if args.dry_run:
            sample = targets[:10]
            print(f'(dry-run) would enqueue email_ids: {sample}'
                  + (' ...' if len(targets) > 10 else ''))
            return 0

        inserted = embedding_enqueue.enqueue_many(targets, reason='backfill')
        print(f'Enqueued: {inserted} job(s) (skipped {len(targets) - inserted} duplicates)')
        return 0
    finally:
        cursor.close()
        conn.close()


if __name__ == '__main__':
    sys.exit(main())
