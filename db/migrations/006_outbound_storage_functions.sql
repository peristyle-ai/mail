-- =============================================================================
-- Migration 006: Security Definer Functions for Outbound Email Storage
-- =============================================================================
--
-- When storing an outbound email, the sender's connection has RLS context
-- set to the sender's user_id. But we also need to:
--   1. Create an Inbox folder for the recipient (different user)
--   2. Insert an email copy into the recipient's Inbox folder
--   3. Insert email_recipients rows for the recipient
--
-- These SECURITY DEFINER functions run with the owner's privileges,
-- allowing cross-user writes while maintaining RLS for normal connections.
--
-- Run as: mal_external (DB owner)
--   psql -U mal_external -h localhost -d mail_server -f db/migrations/006_outbound_storage_functions.sql
--
-- Idempotent: uses CREATE OR REPLACE throughout.
-- =============================================================================

-- ----- Get or create a folder for any user ------------------------------------
-- Used to get/create the recipient's Inbox when storing a local copy.

CREATE OR REPLACE FUNCTION get_or_create_folder(
    p_user_id INTEGER,
    p_folder_name VARCHAR
)
RETURNS INTEGER
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_folder_id INTEGER;
BEGIN
    -- Try to find existing folder
    SELECT id INTO v_folder_id
    FROM folders
    WHERE user_id = p_user_id AND name = p_folder_name;

    IF v_folder_id IS NOT NULL THEN
        RETURN v_folder_id;
    END IF;

    -- Create the folder
    INSERT INTO folders (user_id, name, created_at)
    VALUES (p_user_id, p_folder_name, NOW())
    RETURNING id INTO v_folder_id;

    RETURN v_folder_id;
END;
$$ LANGUAGE plpgsql;

-- ----- Insert email into any folder -------------------------------------------
-- Used to insert a copy of the email into the recipient's Inbox.

CREATE OR REPLACE FUNCTION insert_email_to_folder(
    p_sender_id INTEGER,
    p_recipient_id INTEGER,
    p_source_email_id INTEGER,
    p_folder_id INTEGER,
    p_subject VARCHAR,
    p_body TEXT,
    p_body_html TEXT,
    p_raw_email TEXT,
    p_headers TEXT,
    p_is_read BOOLEAN,
    p_message_id VARCHAR,
    p_in_reply_to VARCHAR,
    p_references_chain TEXT,
    p_thread_id UUID,
    p_subject_normalized VARCHAR
)
RETURNS INTEGER
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_email_id INTEGER;
BEGIN
    INSERT INTO emails
        (sender_id, recipient_id, source_email_id, folder_id, subject, body,
         body_html, raw_email, headers, created_at, is_read,
         message_id, in_reply_to, references_chain, thread_id, subject_normalized)
    VALUES
        (p_sender_id, p_recipient_id, p_source_email_id, p_folder_id, p_subject, p_body,
         p_body_html, p_raw_email, p_headers, NOW(), p_is_read,
         p_message_id, p_in_reply_to, p_references_chain, p_thread_id, p_subject_normalized)
    RETURNING id INTO v_email_id;

    RETURN v_email_id;
END;
$$ LANGUAGE plpgsql;

-- ----- Insert email recipient row ----------------------------------------------

CREATE OR REPLACE FUNCTION insert_email_recipient(
    p_email_id INTEGER,
    p_user_id INTEGER,
    p_recipient_email VARCHAR,
    p_recipient_type VARCHAR
)
RETURNS VOID
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    INSERT INTO email_recipients (email_id, user_id, recipient_email, recipient_type)
    VALUES (p_email_id, p_user_id, p_recipient_email, p_recipient_type);
END;
$$ LANGUAGE plpgsql;

-- ----- Insert outbound queue entry ----------------------------------------------

CREATE OR REPLACE FUNCTION insert_outbound_queue(
    p_email_id INTEGER,
    p_recipient_email VARCHAR,
    p_recipient_domain VARCHAR
)
RETURNS INTEGER
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_queue_id INTEGER;
BEGIN
    INSERT INTO outbound_queue
        (email_id, recipient_email, recipient_domain, status, created_at)
    VALUES
        (p_email_id, p_recipient_email, p_recipient_domain, 'pending', NOW())
    RETURNING id INTO v_queue_id;

    RETURN v_queue_id;
END;
$$ LANGUAGE plpgsql;

-- ----- Grant execute to mail_external_app -------------------------------------

GRANT EXECUTE ON FUNCTION get_or_create_folder(INTEGER, VARCHAR) TO mail_external_app;
GRANT EXECUTE ON FUNCTION insert_email_to_folder(INTEGER, INTEGER, INTEGER, INTEGER, VARCHAR, TEXT, TEXT, TEXT, TEXT, BOOLEAN, VARCHAR, VARCHAR, TEXT, UUID, VARCHAR) TO mail_external_app;
GRANT EXECUTE ON FUNCTION insert_email_recipient(INTEGER, INTEGER, VARCHAR, VARCHAR) TO mail_external_app;
GRANT EXECUTE ON FUNCTION insert_outbound_queue(INTEGER, VARCHAR, VARCHAR) TO mail_external_app;

-- ----- Insert embedding job (cross-user safe) ----------------------------------

CREATE OR REPLACE FUNCTION insert_embedding_job(p_email_id INTEGER)
RETURNS INTEGER
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_job_id INTEGER;
BEGIN
    -- Skip if there's already a live job
    IF EXISTS (SELECT 1 FROM embedding_jobs WHERE email_id = p_email_id AND status IN ('pending','processing')) THEN
        RETURN NULL;
    END IF;

    INSERT INTO embedding_jobs (email_id, status)
    VALUES (p_email_id, 'pending')
    RETURNING id INTO v_job_id;

    RETURN v_job_id;
END;
$$ LANGUAGE plpgsql;

GRANT EXECUTE ON FUNCTION insert_embedding_job(INTEGER) TO mail_external_app;

-- ----- Copy attachments between emails -----------------------------------------
-- Used to copy attachments from the Sent email to each recipient's Inbox copy.

CREATE OR REPLACE FUNCTION copy_attachments_to_email(
    p_source_email_id INTEGER,
    p_target_email_id INTEGER
)
RETURNS INTEGER
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_count INTEGER := 0;
BEGIN
    INSERT INTO attachments (email_id, file_name, file_path, content_type, file_size, created_at)
    SELECT p_target_email_id, file_name, file_path, content_type, file_size, NOW()
    FROM attachments
    WHERE email_id = p_source_email_id;
    
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

GRANT EXECUTE ON FUNCTION copy_attachments_to_email(INTEGER, INTEGER) TO mail_external_app;

-- ----- Insert single attachment record (cross-user safe) -----------------------
-- Used when uploading an attachment to mirror it onto Inbox copies owned by
-- different users.

CREATE OR REPLACE FUNCTION insert_attachment_record(
    p_email_id INTEGER,
    p_user_id INTEGER,
    p_file_name VARCHAR,
    p_content_type VARCHAR,
    p_file_size BIGINT,
    p_file_path VARCHAR
)
RETURNS INTEGER
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_attachment_id INTEGER;
BEGIN
    INSERT INTO attachments (email_id, user_id, file_name, content_type, file_size, file_path, created_at)
    VALUES (p_email_id, p_user_id, p_file_name, p_content_type, p_file_size, p_file_path, NOW())
    RETURNING id INTO v_attachment_id;
    RETURN v_attachment_id;
END;
$$ LANGUAGE plpgsql;

GRANT EXECUTE ON FUNCTION insert_attachment_record(INTEGER, INTEGER, VARCHAR, VARCHAR, BIGINT, VARCHAR) TO mail_external_app;

-- ----- Smoke check ------------------------------------------------------------

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'get_or_create_folder') THEN
        RAISE EXCEPTION 'Migration 006 failed: get_or_create_folder not created';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'insert_email_to_folder') THEN
        RAISE EXCEPTION 'Migration 006 failed: insert_email_to_folder not created';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'insert_email_recipient') THEN
        RAISE EXCEPTION 'Migration 006 failed: insert_email_recipient not created';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'insert_outbound_queue') THEN
        RAISE EXCEPTION 'Migration 006 failed: insert_outbound_queue not created';
    END IF;
    RAISE NOTICE 'Migration 006: Outbound storage functions created successfully';
END $$;
