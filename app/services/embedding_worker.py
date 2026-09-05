"""
Embedding worker daemon.

Long-running single-threaded process. Pulls rows out of `embedding_jobs`
using `SELECT FOR UPDATE SKIP LOCKED` (so multiple workers could run
concurrently without coordination), processes them, and writes:

    * `emails.subject_embedding`        — halfvec(1024)
    * `email_chunks`                    — N rows per email (body chunks + embedding)

Runs as a `systemd --user` service (mail-server-embeddings.service).
Restarts on failure, logs to journald. No Flask, no SMTP — just Postgres
and the GPU server.

Run modes (for scripts/run_embedding_worker.py):

    loop     — daemon mode, polls forever (the systemd default)
    once     — process everything currently pending, then exit (used by
               tests + ops one-shot catch-up runs)

Adaptive polling: sleep 1s when there's work, ramp up to 10s when idle
for >30s. Keeps DB load minimal at quiet times without sacrificing
latency during inbound bursts.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from dataclasses import dataclass
from typing import List, Optional, Sequence

from psycopg2.extras import RealDictCursor

from app.db import get_db_connection
from app.services.embedding_service import (
    EmbeddingConfig,
    EmbeddingError,
    EmbeddingService,
)
from app.utils.chunking import chunk_email
from app.utils.embedding_enqueue import (
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_PROCESSING,
    _load_enabled_folder_names,
)

logger = logging.getLogger(__name__)


# Worker tuning. These are read once at process start; tweak via env if
# you want a different ceiling in tests.
BATCH_SIZE = int(os.environ.get('EMBEDDING_WORKER_BATCH', '8'))
IDLE_SLEEP_BASE_SECONDS = 1.0
IDLE_SLEEP_CAP_SECONDS = 10.0
IDLE_RAMP_AFTER_SECONDS = 30.0

# Job-level retry policy. Once a job has failed this many times, mark it
# `failed` permanently so it doesn't keep getting picked up.
MAX_JOB_ATTEMPTS = 5


@dataclass
class ClaimedJob:
    job_id: int
    email_id: int
    attempts: int


class EmbeddingWorker:
    """The worker. Construct, then call `.run_forever()` or `.run_once()`."""

    def __init__(self, embedding: Optional[EmbeddingService] = None) -> None:
        self.embedding = embedding or EmbeddingService()
        self._stop = False
        self._idle_since: Optional[float] = None

    # --- lifecycle -----------------------------------------------------------

    def request_stop(self, *_: object) -> None:
        logger.info("embedding worker stop requested")
        self._stop = True

    def run_forever(self) -> int:
        """Daemon entrypoint. Returns 0 on clean shutdown, non-zero on
        unhandled failure."""
        signal.signal(signal.SIGTERM, self.request_stop)
        signal.signal(signal.SIGINT, self.request_stop)
        logger.info(
            "embedding worker starting (batch=%d, model=%s, dims=%d, base_url=%s)",
            BATCH_SIZE, self.embedding.config.model,
            self.embedding.config.dimensions, self.embedding.config.base_url,
        )
        idle_sleep = IDLE_SLEEP_BASE_SECONDS
        while not self._stop:
            try:
                processed = self.drain_once()
            except Exception:
                # Drain errors should not kill the worker. Log + back off.
                logger.exception("worker drain failed; backing off")
                processed = 0
                idle_sleep = IDLE_SLEEP_CAP_SECONDS
                time.sleep(idle_sleep)
                continue
            if processed == 0:
                # Nothing to do — ramp up the sleep interval so we don't
                # hammer Postgres at idle.
                now = time.monotonic()
                if self._idle_since is None:
                    self._idle_since = now
                idle_for = now - self._idle_since
                if idle_for >= IDLE_RAMP_AFTER_SECONDS:
                    idle_sleep = min(IDLE_SLEEP_CAP_SECONDS,
                                     idle_sleep * 1.5)
                time.sleep(idle_sleep)
                continue
            # We did real work — reset the idle ramp.
            self._idle_since = None
            idle_sleep = IDLE_SLEEP_BASE_SECONDS
        logger.info("embedding worker exiting cleanly")
        self.embedding.close()
        return 0

    def run_once(self) -> int:
        """Process everything currently due and return. Used by ops
        catch-up runs and the backfill script's hot loop."""
        processed = 0
        while True:
            n = self.drain_once()
            processed += n
            if n == 0:
                break
        return processed

    # --- main loop body ------------------------------------------------------

    def drain_once(self) -> int:
        """Claim up to BATCH_SIZE jobs, process them, return the count."""
        conn = get_db_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                claimed: List[ClaimedJob] = self._claim_jobs(cursor)
                if not claimed:
                    conn.commit()
                    return 0

                # Process each job in its own subtransaction so one bad
                # email doesn't fail the whole batch.
                for job in claimed:
                    self._process_one(conn, cursor, job)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return len(claimed)

    def _claim_jobs(self, cursor) -> List[ClaimedJob]:
        """SELECT FOR UPDATE SKIP LOCKED + UPDATE to processing."""
        cursor.execute(
            '''SELECT id, email_id, attempts
               FROM embedding_jobs
               WHERE status = 'pending'
                 AND next_retry_at <= NOW()
                 AND attempts < %s
               ORDER BY id
               LIMIT %s
               FOR UPDATE SKIP LOCKED''',
            (MAX_JOB_ATTEMPTS, BATCH_SIZE),
        )
        rows = cursor.fetchall()
        if not rows:
            return []
        ids = [r['id'] for r in rows]
        cursor.execute(
            '''UPDATE embedding_jobs
               SET status = 'processing',
                   started_at = NOW(),
                   attempts = attempts + 1
               WHERE id = ANY(%s)''',
            (ids,),
        )
        return [ClaimedJob(job_id=r['id'], email_id=r['email_id'],
                            attempts=r['attempts'] + 1) for r in rows]

    def _process_one(self, conn, cursor, job: ClaimedJob) -> None:
        """Embed one email. Updates subject_embedding + email_chunks, marks
        the job done. On retryable failure, reschedules with backoff. If
        the email has nothing to embed (empty subject + folder not
        enabled), marks the job `skipped` so backfill won't re-enqueue."""
        try:
            outcome = self._embed_email(cursor, job.email_id)
        except EmbeddingError as e:
            self._mark_failed(cursor, job, str(e))
            logger.warning(
                "embedding job %d (email %d) failed attempt %d: %s",
                job.job_id, job.email_id, job.attempts, e,
            )
            return
        except Exception as e:
            # Unexpected — log full traceback, mark failed, don't crash the
            # worker.
            logger.exception("embedding job %d crashed", job.job_id)
            self._mark_failed(cursor, job, f"unexpected: {e!r}")
            return
        if outcome == 'skipped':
            self._mark_skipped(cursor, job, 'no-op: empty subject, folder not enabled')
        else:
            self._mark_done(cursor, job)

    def _embed_email(self, cursor, email_id: int) -> str:
        """Fetch the email + folder, embed subject, chunk body, embed
        chunks, write everything. Returns 'done' if any work was done,
        'skipped' if there was nothing to embed."""
        cursor.execute(
            '''SELECT e.id, e.subject, e.body, e.body_html, e.folder_id,
                      f.name AS folder_name
               FROM emails e
               LEFT JOIN folders f ON f.id = e.folder_id
               WHERE e.id = %s''',
            (email_id,),
        )
        email = cursor.fetchone()
        if email is None:
            raise EmbeddingError(f"email {email_id} no longer exists")

        enabled_folders = _load_enabled_folder_names()
        folder_name = (email.get('folder_name') or '').casefold()
        body_enabled = folder_name in enabled_folders

        did_work = False

        # ----- subject -----
        subject = (email.get('subject') or '').strip()
        if subject:
            subj_vec = self.embedding.embed_one(subject)
            cursor.execute(
                '''UPDATE emails
                   SET subject_embedding = %s::halfvec
                   WHERE id = %s''',
                (subj_vec, email_id),
            )
            did_work = True

        # ----- body chunks -----
        if body_enabled:
            chunks = chunk_email(
                body=email.get('body') or '',
                body_html=email.get('body_html') or '',
            )
            if chunks:
                texts = [c.text for c in chunks]
                vectors = self.embedding.embed_batch(texts)
                # Upsert each chunk. Using INSERT ... ON CONFLICT keeps the
                # worker idempotent — re-runs don't double-write.
                for chunk, vec in zip(chunks, vectors):
                    cursor.execute(
                        '''INSERT INTO email_chunks
                            (email_id, folder_id, chunk_index, content,
                             embedding, token_count, updated_at)
                           VALUES (%s, %s, %s, %s, %s::halfvec, %s, NOW())
                           ON CONFLICT (email_id, chunk_index) DO UPDATE
                           SET folder_id   = EXCLUDED.folder_id,
                               content     = EXCLUDED.content,
                               embedding   = EXCLUDED.embedding,
                               token_count = EXCLUDED.token_count,
                               updated_at  = NOW()''',
                        (email_id, email.get('folder_id'), chunk.index,
                         chunk.text, vec, chunk.token_count),
                    )
                did_work = True

        return 'done' if did_work else 'skipped'

    def _mark_done(self, cursor, job: ClaimedJob) -> None:
        cursor.execute(
            '''UPDATE embedding_jobs
               SET status = 'done',
                   completed_at = NOW(),
                   last_error = NULL
               WHERE id = %s''',
            (job.job_id,),
        )

    def _mark_failed(self, cursor, job: ClaimedJob, error: str) -> None:
        # Decide whether this attempt is terminal (attempts >= MAX) or just
        # needs a backoff reschedule.
        terminal = job.attempts >= MAX_JOB_ATTEMPTS
        if terminal:
            cursor.execute(
                '''UPDATE embedding_jobs
                   SET status = 'failed',
                       completed_at = NOW(),
                       last_error = %s
                   WHERE id = %s''',
                (error[:1000], job.job_id),
            )
        else:
            # Exponential backoff: 5s, 30s, 2m, 10m, 30m, ...
            delay_s = min(30 * 60, 5 * (6 ** max(0, job.attempts - 1)))
            cursor.execute(
                '''UPDATE embedding_jobs
                   SET status = 'pending',
                       next_retry_at = NOW() + (%s || ' seconds')::interval,
                       last_error = %s
                   WHERE id = %s''',
                (str(delay_s), error[:1000], job.job_id),
            )

    def _mark_skipped(self, cursor, job: ClaimedJob, reason: str) -> None:
        """Mark a job `skipped` — there was nothing to embed (empty
        subject, folder not enabled). The backfill script excludes skipped
        rows so we don't re-enqueue the same dead-end emails."""
        cursor.execute(
            '''UPDATE embedding_jobs
               SET status = 'skipped',
                   completed_at = NOW(),
                   last_error = %s
               WHERE id = %s''',
            (reason[:1000], job.job_id),
        )


def main() -> int:
    """CLI entrypoint used by scripts/run_embedding_worker.py."""
    logging.basicConfig(
        level=os.environ.get('LOG_LEVEL', 'INFO'),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    )
    worker = EmbeddingWorker()
    mode = os.environ.get('EMBEDDING_WORKER_MODE', 'loop')
    if mode == 'once':
        return worker.run_once()
    return worker.run_forever()


if __name__ == '__main__':
    sys.exit(main())
