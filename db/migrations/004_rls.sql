-- =============================================================================
-- Migration 004: Row-Level Security (RLS) for multi-tenant isolation
-- =============================================================================
--
-- Enables RLS on all user-data tables so that the database itself enforces
-- tenant isolation, not just the application layer.
--
-- The app sets `app.user_id` as a custom GUC after JWT authentication:
--   SET app.user_id = '268';
--
-- All subsequent queries in that session automatically only see rows
-- belonging to that user.
--
-- Run as: mal_external (DB owner)
--   psql -U mal_external -h localhost -d mail_server -f db/migrations/004_rls.sql
--
-- Idempotent: uses IF NOT EXISTS / CREATE OR REPLACE throughout.
-- =============================================================================

-- ----- Helper function to get current user ID from GUC ----------------------

CREATE OR REPLACE FUNCTION current_app_user_id() RETURNS INTEGER AS $$
BEGIN
    RETURN current_setting('app.user_id', TRUE)::INTEGER;
EXCEPTION WHEN OTHERS THEN
    RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE;

-- ----- folders ---------------------------------------------------------------

ALTER TABLE folders ENABLE ROW LEVEL SECURITY;

CREATE POLICY folders_isolation ON folders
    FOR ALL
    TO mail_external_app
    USING (user_id = current_app_user_id())
    WITH CHECK (user_id = current_app_user_id());

-- ----- emails ----------------------------------------------------------------

ALTER TABLE emails ENABLE ROW LEVEL SECURITY;

-- Users can see emails in folders they own, OR emails where they are the
-- sender (for sent items that may have been moved to a shared folder).
CREATE POLICY emails_isolation ON emails
    FOR ALL
    TO mail_external_app
    USING (
        folder_id IN (SELECT id FROM folders WHERE user_id = current_app_user_id())
        OR sender_id = current_app_user_id()
    )
    WITH CHECK (
        folder_id IN (SELECT id FROM folders WHERE user_id = current_app_user_id())
        OR sender_id = current_app_user_id()
    );

-- ----- email_recipients -------------------------------------------------------

ALTER TABLE email_recipients ENABLE ROW LEVEL SECURITY;

-- Users can see recipient rows for emails they can see.
CREATE POLICY email_recipients_isolation ON email_recipients
    FOR ALL
    TO mail_external_app
    USING (
        email_id IN (
            SELECT e.id FROM emails e
            JOIN folders f ON e.folder_id = f.id
            WHERE f.user_id = current_app_user_id()
        )
    )
    WITH CHECK (
        email_id IN (
            SELECT e.id FROM emails e
            JOIN folders f ON e.folder_id = f.id
            WHERE f.user_id = current_app_user_id()
        )
    );

-- ----- attachments ------------------------------------------------------------

ALTER TABLE attachments ENABLE ROW LEVEL SECURITY;

-- Users can see attachments for emails they can see.
CREATE POLICY attachments_isolation ON attachments
    FOR ALL
    TO mail_external_app
    USING (
        email_id IN (
            SELECT e.id FROM emails e
            JOIN folders f ON e.folder_id = f.id
            WHERE f.user_id = current_app_user_id()
        )
    )
    WITH CHECK (
        email_id IN (
            SELECT e.id FROM emails e
            JOIN folders f ON e.folder_id = f.id
            WHERE f.user_id = current_app_user_id()
        )
    );

-- ----- email_chunks -----------------------------------------------------------

ALTER TABLE email_chunks ENABLE ROW LEVEL SECURITY;

-- Users can see chunks for emails they can see.
CREATE POLICY email_chunks_isolation ON email_chunks
    FOR ALL
    TO mail_external_app
    USING (
        email_id IN (
            SELECT e.id FROM emails e
            JOIN folders f ON e.folder_id = f.id
            WHERE f.user_id = current_app_user_id()
        )
    )
    WITH CHECK (
        email_id IN (
            SELECT e.id FROM emails e
            JOIN folders f ON e.folder_id = f.id
            WHERE f.user_id = current_app_user_id()
        )
    );

-- ----- embedding_jobs ---------------------------------------------------------

ALTER TABLE embedding_jobs ENABLE ROW LEVEL SECURITY;

-- Users can see jobs for emails they can see.
CREATE POLICY embedding_jobs_isolation ON embedding_jobs
    FOR ALL
    TO mail_external_app
    USING (
        email_id IN (
            SELECT e.id FROM emails e
            JOIN folders f ON e.folder_id = f.id
            WHERE f.user_id = current_app_user_id()
        )
    )
    WITH CHECK (
        email_id IN (
            SELECT e.id FROM emails e
            JOIN folders f ON e.folder_id = f.id
            WHERE f.user_id = current_app_user_id()
        )
    );

-- ----- outbound_queue ---------------------------------------------------------

ALTER TABLE outbound_queue ENABLE ROW LEVEL SECURITY;

-- Users can see queue entries for emails they can see.
CREATE POLICY outbound_queue_isolation ON outbound_queue
    FOR ALL
    TO mail_external_app
    USING (
        email_id IN (
            SELECT e.id FROM emails e
            JOIN folders f ON e.folder_id = f.id
            WHERE f.user_id = current_app_user_id()
        )
    )
    WITH CHECK (
        email_id IN (
            SELECT e.id FROM emails e
            JOIN folders f ON e.folder_id = f.id
            WHERE f.user_id = current_app_user_id()
        )
    );

-- ----- delivery_logs ----------------------------------------------------------

ALTER TABLE delivery_logs ENABLE ROW LEVEL SECURITY;

-- Users can see delivery logs for emails they can see.
CREATE POLICY delivery_logs_isolation ON delivery_logs
    FOR ALL
    TO mail_external_app
    USING (
        email_id IN (
            SELECT e.id FROM emails e
            JOIN folders f ON e.folder_id = f.id
            WHERE f.user_id = current_app_user_id()
        )
    )
    WITH CHECK (
        email_id IN (
            SELECT e.id FROM emails e
            JOIN folders f ON e.folder_id = f.id
            WHERE f.user_id = current_app_user_id()
        )
    );

-- ----- Tables that DON'T need RLS (shared/system tables) ---------------------
--
-- users              — shared (external senders are visible to all)
-- domains            — shared (domain config is global)
-- ip_blacklist       — shared (security infrastructure)
-- sender_blocklist   — shared (security infrastructure)
-- greylist           — shared (security infrastructure)
-- rate_limit_violations — shared (security infrastructure)
-- rate_limit_attempts   — shared (security infrastructure)
-- major_providers    — shared (reference data)

-- ----- Smoke check ------------------------------------------------------------

DO $$
DECLARE
    tbl TEXT;
    missing BOOLEAN;
BEGIN
    FOR tbl IN SELECT unnest(ARRAY[
        'folders', 'emails', 'email_recipients', 'attachments',
        'email_chunks', 'embedding_jobs', 'outbound_queue', 'delivery_logs'
    ]) LOOP
        SELECT NOT EXISTS (
            SELECT 1 FROM pg_tables
            WHERE schemaname = 'public' AND tablename = tbl AND rowsecurity = TRUE
        ) INTO missing;
        IF missing THEN
            RAISE EXCEPTION 'Migration 004 failed: RLS not enabled on %', tbl;
        END IF;
    END LOOP;
    RAISE NOTICE 'Migration 004: RLS enabled on all 8 user-data tables';
END $$;
