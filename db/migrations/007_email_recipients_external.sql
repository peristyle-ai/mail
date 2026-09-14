-- =============================================================================
-- Migration 007: Add recipient_email to email_recipients for external recipients
-- =============================================================================
--
-- The outbound email storage path (migration 006 functions) inserts
-- recipient_email for external recipients and allows user_id to be NULL.
-- The canonical schema was missing recipient_email and had user_id NOT NULL.
--
-- This migration aligns the schema with the actual code requirements.
--
-- Run as: DB owner (postgres or mal_external)
--   psql -U <owner> -h localhost -d mail_server -f db/migrations/007_email_recipients_external.sql
--
-- Idempotent: uses IF NOT EXISTS / conditional DDL throughout.
-- =============================================================================

-- Add recipient_email column if it doesn't exist
ALTER TABLE email_recipients ADD COLUMN IF NOT EXISTS recipient_email TEXT;

-- Allow user_id to be NULL (external recipients have no local user)
ALTER TABLE email_recipients ALTER COLUMN user_id DROP NOT NULL;

-- Add check constraint: at least one of user_id or recipient_email must be set
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'email_recipients_at_least_one_target'
    ) THEN
        ALTER TABLE email_recipients
        ADD CONSTRAINT email_recipients_at_least_one_target
        CHECK (user_id IS NOT NULL OR recipient_email IS NOT NULL);
    END IF;
END $$;

-- Smoke check
DO $$
BEGIN
    -- Verify recipient_email column exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'email_recipients' AND column_name = 'recipient_email'
    ) THEN
        RAISE EXCEPTION 'Migration 007 failed: recipient_email column not created';
    END IF;

    -- Verify user_id is nullable
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'email_recipients' AND column_name = 'user_id' AND is_nullable = 'NO'
    ) THEN
        RAISE EXCEPTION 'Migration 007 failed: user_id is still NOT NULL';
    END IF;

    RAISE NOTICE 'Migration 007: email_recipients updated for external recipients';
END $$;
