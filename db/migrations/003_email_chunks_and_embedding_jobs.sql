-- =============================================================================
-- Migration 003: Email chunks + embedding jobs (PR1 of embeddings rollout)
-- =============================================================================
--
-- Adds the tables that power async semantic + trigram search:
--
--   email_chunks
--       One row per chunk of an email body. Each chunk has:
--         - `content`         the chunk text (snippet, used for keyword /
--                              trigram search and for showing in search
--                              results)
--         - `embedding`       halfvec(1024) from the Qwen3-Embedding-4B
--                              server, served via the local text-embeddings-
--                              router on 127.0.0.1:8080
--       Indexes:
--         - UNIQUE(email_id, chunk_index)   for idempotent upsert
--         - HNSW on embedding               for cosine-similarity search
--         - GIN trigram on content          for fast keyword / phrase search
--
--   embedding_jobs
--       Postgres-backed queue consumed by the separate embedding worker
--       (systemd --user service: mail-server-embeddings.service).
--       Mail-server hooks (POST /inbound, SMTP DATA, POST /api/emails,
--       POST /api/emails/<id>/move) insert a `pending` row here when an
--       email lands in a folder with embedding enabled (default:
--       Processed + Sent; configurable).
--
-- Both new tables are scoped per-folder so a multi-user DB doesn't leak
-- across users.  (We index on email_id and folder_id; ownership is enforced
-- upstream by the worker joining emails/folders to user_id.)
--
-- Run order (production):
--
--   # Option A (zero-downtime, recommended):
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "
--       CREATE EXTENSION IF NOT EXISTS vector;
--       CREATE EXTENSION IF NOT EXISTS pg_trgm;
--   "
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "
--       CREATE TABLE IF NOT EXISTS email_chunks (
--           id          BIGSERIAL PRIMARY KEY,
--           email_id    INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
--           folder_id   INTEGER REFERENCES folders(id) ON DELETE SET NULL,
--           chunk_index INTEGER NOT NULL,
--           content     TEXT NOT NULL,
--           embedding   halfvec(1024),
--           token_count INTEGER,
--           created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
--           updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
--           UNIQUE(email_id, chunk_index)
--       );
--   "
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "
--       CREATE INDEX IF NOT EXISTS idx_email_chunks_email_id ON email_chunks(email_id);
--       CREATE INDEX IF NOT EXISTS idx_email_chunks_folder_id ON email_chunks(folder_id) WHERE folder_id IS NOT NULL;
--   "
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "
--       CREATE INDEX IF NOT EXISTS idx_email_chunks_embedding_hnsw
--           ON email_chunks USING hnsw (embedding halfvec_cosine_ops)
--           WITH (m = 16, ef_construction = 64);
--   "
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "
--       CREATE INDEX IF NOT EXISTS idx_email_chunks_content_trgm
--           ON email_chunks USING gin (content gin_trgm_ops);
--   "
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "
--       CREATE TABLE IF NOT EXISTS embedding_jobs (
--           id            BIGSERIAL PRIMARY KEY,
--           email_id      INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
--           enqueued_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
--           next_retry_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
--           started_at    TIMESTAMPTZ,
--           completed_at  TIMESTAMPTZ,
--           status        TEXT NOT NULL DEFAULT 'pending'
--                             CHECK (status IN ('pending','processing','done','failed','skipped')),
--           attempts      INTEGER NOT NULL DEFAULT 0,
--           last_error    TEXT
--       );
--   "
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "
--       CREATE INDEX IF NOT EXISTS idx_embedding_jobs_pending
--           ON embedding_jobs(next_retry_at) WHERE status = 'pending';
--   "
--
--   # Option B (single transaction; what this migration file does):
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/migrations/003_email_chunks_and_embedding_jobs.sql
--   # then:
--   systemctl --user daemon-reload
--   systemctl --user enable --now mail-server-embeddings.service
--   python scripts/backfill_embeddings.py --status            # preview
--   python scripts/backfill_embeddings.py --dry-run --limit 10
--   python scripts/backfill_embeddings.py                       # full backfill
--
-- Idempotent: every CREATE / ALTER uses IF NOT EXISTS so re-running is safe.
-- =============================================================================

-- ----- Required extensions (no-op if already installed) ----------------------

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ----- email_chunks ---------------------------------------------------------

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

CREATE INDEX IF NOT EXISTS idx_email_chunks_folder_id
    ON email_chunks(folder_id) WHERE folder_id IS NOT NULL;

-- HNSW on halfvec(1024) — 2048 bytes/row, comfortably under pgvector's
-- page limit (see MEMORY.md pgvector halfvec dim ceiling, 2026-08-16).
CREATE INDEX IF NOT EXISTS idx_email_chunks_embedding_hnsw
    ON email_chunks USING hnsw (embedding halfvec_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Trigram keyword search over chunk content (for the "show me emails
-- containing the exact word X" path of the search endpoint in PR2).
CREATE INDEX IF NOT EXISTS idx_email_chunks_content_trgm
    ON email_chunks USING gin (content gin_trgm_ops);

-- ----- embedding_jobs --------------------------------------------------------

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

-- The worker's claim query is:
--   SELECT ... FROM embedding_jobs
--   WHERE status='pending' AND next_retry_at <= NOW()
--   ORDER BY id LIMIT N FOR UPDATE SKIP LOCKED
-- A partial index on `next_retry_at WHERE status='pending'` keeps the scan
-- cheap as the table grows (done / failed rows are skipped).
CREATE INDEX IF NOT EXISTS idx_embedding_jobs_pending
    ON embedding_jobs(next_retry_at) WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_embedding_jobs_email_id
    ON embedding_jobs(email_id);

-- ----- Smoke check -----------------------------------------------------------

DO $$
DECLARE
    missing BOOLEAN;
BEGIN
    SELECT NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'email_chunks'
    )
    INTO missing;
    IF missing THEN
        RAISE EXCEPTION 'Migration 003 failed: email_chunks not created';
    END IF;

    SELECT NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'embedding_jobs'
    )
    INTO missing;
    IF missing THEN
        RAISE EXCEPTION 'Migration 003 failed: embedding_jobs not created';
    END IF;
END $$;
