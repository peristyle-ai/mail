"""
Enqueue helper for the embedding worker queue.

Every place an email lands (POST /inbound, SMTP DATA, POST /api/emails,
POST /api/emails/<id>/move) calls `enqueue_embedding_job(email_id)` after
committing its insert. The worker drains the queue asynchronously.

This module is intentionally tiny and self-contained so the four call
sites can import it without pulling in Flask or any other framework.

Per-folder opt-in is handled here, not at the call sites — that keeps the
policy in one place.  A new email in 'Inbox' (default disabled) does not
get enqueued at all.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional, Set

from .chunking import chunk_email
from .db import get_db_connection

logger = logging.getLogger(__name__)


# Statuses for embedding_jobs.status. Kept here so callers don't import
# the worker's constants.
STATUS_PENDING = 'pending'
STATUS_PROCESSING = 'processing'
STATUS_DONE = 'done'
STATUS_FAILED = 'failed'
STATUS_SKIPPED = 'skipped'


def _load_enabled_folder_names() -> Set[str]:
    """Return the set of folder names that have embedding enabled.

    Reads from config.yaml's `embedding.folders.<Name>.enabled` map. Folders
    not mentioned default to disabled. Returns a set of uppercase folder
    names for case-insensitive matching (folder names in the DB are
    mixed-case like 'Inbox' / 'Sent' / 'Processed').
    """
    # Lazy import so this module stays Flask-free.
    from config import get_config
    cfg = get_config()
    block = getattr(cfg, '_config', {}).get('embedding') or {}
    folders = block.get('folders') or {}
    enabled: Set[str] = set()
    for name, opts in folders.items():
        if isinstance(opts, dict) and opts.get('enabled', False):
            enabled.add(str(name).casefold())
    return enabled


def _resolve_folder_name(folder_id: Optional[int], user_id: Optional[int]) -> str:
    """Best-effort lookup of the folder name. Returns '' if not found."""
    if folder_id is None:
        return ''
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if user_id is not None:
            cursor.execute(
                'SELECT name FROM folders WHERE id = %s AND user_id = %s',
                (folder_id, user_id),
            )
        else:
            cursor.execute('SELECT name FROM folders WHERE id = %s', (folder_id,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return (row['name'] if row else '') or ''
    except Exception as e:
        logger.warning("enqueue: folder name lookup failed for id=%s: %s", folder_id, e)
        return ''


def enqueue_embedding_job(email_id: int, folder_id: Optional[int] = None,
                          user_id: Optional[int] = None,
                          reason: str = 'insert') -> bool:
    """Queue an email for embedding.

    Returns True if a job row was inserted, False if skipped (folder
    not configured for embedding, or email already has a live job).

    The worker will:
        1. Embed the subject  -> update `emails.subject_embedding`
        2. Chunk the body     -> write `email_chunks` rows
        3. Mark the job done

    Subject embedding happens even when the folder isn't configured for
    body chunking — per Mal's direction (2026-09-06): "make consistent
    with the new embedding process".
    """
    folder_name = _resolve_folder_name(folder_id, user_id)
    enabled_folders = _load_enabled_folder_names()

    # Subject embedding always runs (one short text per email, cheap).
    subject_enabled = True

    # Body chunking only when the folder is in the configured set.
    body_enabled = folder_name.casefold() in enabled_folders if folder_name else False

    if not subject_enabled and not body_enabled:
        return False

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Skip if there's already a live (non-terminal) job for this email.
        cursor.execute(
            '''SELECT 1 FROM embedding_jobs
               WHERE email_id = %s AND status IN ('pending','processing')
               LIMIT 1''',
            (email_id,),
        )
        if cursor.fetchone() is not None:
            cursor.close()
            conn.close()
            return False
        cursor.execute(
            '''INSERT INTO embedding_jobs (email_id, status)
               VALUES (%s, 'pending')
               RETURNING id''',
            (email_id,),
        )
        job_id = cursor.fetchone()['id']
        conn.commit()
        cursor.close()
        conn.close()
        logger.info(
            "embedding enqueued: job_id=%s email_id=%s folder=%r reason=%s",
            job_id, email_id, folder_name or '(none)', reason,
        )
        return True
    except Exception as e:
        logger.warning("enqueue_embedding_job failed for email_id=%s: %s", email_id, e)
        return False


def enqueue_many(email_ids: Iterable[int], reason: str = 'backfill') -> int:
    """Bulk-enqueue helper used by the backfill script. Returns rows
    actually inserted (skips duplicates and live jobs)."""
    inserted = 0
    for eid in email_ids:
        # We don't have folder_id/user_id here cheaply — pass None and let
        # the worker decide body vs subject. The worker falls back to
        # enabled-folder lookup using the email's current folder_id.
        if enqueue_embedding_job(int(eid), folder_id=None, user_id=None, reason=reason):
            inserted += 1
    return inserted
