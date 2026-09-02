-- =============================================================================
-- Migration 002: Email threading support
-- =============================================================================
--
-- Adds RFC 2822 threading fields to the `emails` table:
--   * message_id         - this message's Message-ID (without angle brackets)
--   * in_reply_to        - parent Message-ID (single value, nullable)
--   * references_chain   - space-separated Message-ID chain (nullable).
--                          Named `references_chain` because `references` is a
--                          reserved SQL keyword (foreign-key clause) and would
--                          need to be quoted everywhere it appears.
--   * thread_id          - UUID; same for every message in a thread (Sent +
--                          Inbox copies of the same logical message share one)
--   * subject_normalized - pre-computed normalized subject (subject fallback
--                          bucket key; NULL when threaded by References/
--                          In-Reply-To and we never needed it)
--
-- All new columns are NULL-able so the ALTER TABLE is instantaneous on any
-- existing data. The backfill script (scripts/backfill_threads.py) fills them
-- from raw_email / headers.
--
-- Run order (production):
--
--   # Option A (zero-downtime, recommended for large tables):
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "
--       ALTER TABLE emails ADD COLUMN IF NOT EXISTS message_id  VARCHAR(500);
--       ALTER TABLE emails ADD COLUMN IF NOT EXISTS in_reply_to VARCHAR(500);
--       ALTER TABLE emails ADD COLUMN IF NOT EXISTS references  TEXT;
--       ALTER TABLE emails ADD COLUMN IF NOT EXISTS thread_id   UUID;
--       ALTER TABLE emails ADD COLUMN IF NOT EXISTS subject_normalized VARCHAR(500);
--   "
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_emails_message_id             ON emails(message_id);"
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_emails_in_reply_to_where    ON emails(in_reply_to) WHERE in_reply_to IS NOT NULL;"
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_emails_thread_id            ON emails(thread_id);"
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_emails_subject_normalized   ON emails(subject_normalized);"
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_emails_references_trgm     ON emails USING gin (references_chain gin_trgm_ops);"
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
--   python scripts/backfill_threads.py
--
--   # Option B (small DBs, single transaction; what this migration file does):
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/migrations/002_email_threading.sql
--   python scripts/backfill_threads.py
--
-- Idempotent: every CREATE / ALTER uses IF NOT EXISTS so re-running is safe.
-- =============================================================================

-- ----- New columns ----------------------------------------------------------

ALTER TABLE emails
    ADD COLUMN IF NOT EXISTS message_id          VARCHAR(500),
    ADD COLUMN IF NOT EXISTS in_reply_to         VARCHAR(500),
    ADD COLUMN IF NOT EXISTS references_chain    TEXT,
    ADD COLUMN IF NOT EXISTS thread_id           UUID,
    ADD COLUMN IF NOT EXISTS subject_normalized  VARCHAR(500);

-- ----- Required extension ---------------------------------------------------

-- pg_trgm powers the GIN trigram index on `references`. If the DB role can't
-- CREATE EXTENSION, run this manually as a superuser first. The plain btree
-- index on `message_id` already covers the most common parent lookup, so the
-- backfill works even without the GIN index.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ----- Indexes --------------------------------------------------------------
--
-- All four are IF NOT EXISTS so re-running is safe. For zero-downtime on a
-- large table, prefer the CONCURRENTLY variants in the run-order comments
-- above (they cannot run inside a transaction).

-- Parent lookup: "find the email whose Message-ID equals X" (one per email).
-- Non-unique on purpose: local delivery creates Sent + Inbox copies that
-- share a Message-ID.
CREATE INDEX IF NOT EXISTS idx_emails_message_id
    ON emails(message_id);

-- Most replies have a parent; partial index keeps it small.
CREATE INDEX IF NOT EXISTS idx_emails_in_reply_to_where
    ON emails(in_reply_to)
    WHERE in_reply_to IS NOT NULL;

-- Every /api/threads query filters by thread_id.
CREATE INDEX IF NOT EXISTS idx_emails_thread_id
    ON emails(thread_id);

-- Subject-fallback bucket lookups (only populated for rows threaded by
-- subject; partial index keeps it tiny in practice).
CREATE INDEX IF NOT EXISTS idx_emails_subject_normalized
    ON emails(subject_normalized)
    WHERE subject_normalized IS NOT NULL;

-- "Find every email whose References chain mentions X" — used by the
-- backfill when reconstructing threads whose parent is missing. GIN trigram
-- lets us do `references_chain LIKE '%<id>%'` cheaply.
CREATE INDEX IF NOT EXISTS idx_emails_references_trgm
    ON emails USING gin (references_chain gin_trgm_ops);

-- ----- Smoke check ----------------------------------------------------------

DO $$
DECLARE
    missing BOOLEAN;
BEGIN
    -- If the `emails` table doesn't exist yet (e.g. test DB seeded
    -- afterwards), skip the check. Otherwise, complain.
    SELECT NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'emails' AND column_name = 'thread_id'
    )
    INTO missing;
    IF missing THEN
        IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'emails') THEN
            RAISE EXCEPTION 'Migration 002 failed: emails.thread_id not created';
        ELSE
            RAISE NOTICE 'Migration 002: emails table not present, skipping smoke check';
        END IF;
    END IF;
END $$;