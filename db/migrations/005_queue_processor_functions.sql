-- =============================================================================
-- Migration 005: Security Definer Functions for Queue Processor
-- =============================================================================
--
-- The outbound queue processor runs in a background thread without a user
-- context, so RLS blocks its queries. These SECURITY DEFINER functions
-- run with the owner's privileges, allowing the queue processor to access
-- the data it needs while maintaining RLS for normal user connections.
--
-- Run as: mal_external (DB owner)
--   psql -U mal_external -h localhost -d mail_server -f db/migrations/005_queue_processor_functions.sql
--
-- Idempotent: uses CREATE OR REPLACE throughout.
-- =============================================================================

-- ----- Get pending outbound emails -------------------------------------------
-- Returns pending/retry emails ready for delivery, plus stuck 'sending' emails.

CREATE OR REPLACE FUNCTION get_pending_outbound_emails(
    p_now TIMESTAMPTZ,
    p_stuck_threshold TIMESTAMPTZ,
    p_limit INTEGER DEFAULT 10
)
RETURNS TABLE (
    id INTEGER,
    email_id INTEGER,
    recipient_email VARCHAR,
    recipient_domain VARCHAR,
    attempt_count INTEGER
)
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    RETURN QUERY
    SELECT 
        oq.id,
        oq.email_id,
        oq.recipient_email,
        oq.recipient_domain,
        oq.attempt_count
    FROM outbound_queue oq
    WHERE (
        oq.status IN ('pending', 'retry')
        AND (oq.next_attempt IS NULL OR oq.next_attempt <= p_now)
    ) OR (
        oq.status = 'sending'
        AND oq.last_attempt < p_stuck_threshold
    )
    ORDER BY oq.created_at
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;

-- ----- Get email for delivery -------------------------------------------------
-- Returns email content needed for delivery. Only returns the row if the
-- email exists (no user filtering - the queue processor needs access).

CREATE OR REPLACE FUNCTION get_email_for_delivery(p_email_id INTEGER)
RETURNS TABLE (
    id INTEGER,
    sender_id INTEGER,
    subject VARCHAR,
    body TEXT,
    raw_email TEXT,
    headers TEXT
)
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    RETURN QUERY
    SELECT 
        e.id,
        e.sender_id,
        e.subject,
        e.body,
        e.raw_email,
        e.headers
    FROM emails e
    WHERE e.id = p_email_id;
END;
$$ LANGUAGE plpgsql;

-- ----- Get CC recipients for email -------------------------------------------
-- Returns CC recipient emails for a given email.

CREATE OR REPLACE FUNCTION get_email_cc_recipients(
    p_email_id INTEGER,
    p_exclude_user_id INTEGER,
    p_exclude_email VARCHAR
)
RETURNS TABLE (email VARCHAR)
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    RETURN QUERY
    SELECT u.email
    FROM email_recipients er
    JOIN users u ON er.user_id = u.id
    WHERE er.email_id = p_email_id
      AND er.recipient_type = 'cc'
      AND er.user_id != p_exclude_user_id
      AND u.email != p_exclude_email;
END;
$$ LANGUAGE plpgsql;

-- ----- Get sender email address -----------------------------------------------

CREATE OR REPLACE FUNCTION get_user_email(p_user_id INTEGER)
RETURNS VARCHAR
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_email VARCHAR;
BEGIN
    SELECT u.email INTO v_email
    FROM users u
    WHERE u.id = p_user_id;
    RETURN v_email;
END;
$$ LANGUAGE plpgsql;

-- ----- Update queue status ----------------------------------------------------

CREATE OR REPLACE FUNCTION update_queue_status(
    p_queue_id INTEGER,
    p_status VARCHAR,
    p_error_message TEXT DEFAULT NULL,
    p_next_attempt TIMESTAMPTZ DEFAULT NULL,
    p_delivered_at TIMESTAMPTZ DEFAULT NULL
)
RETURNS VOID
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    UPDATE outbound_queue
    SET status = p_status,
        error_message = COALESCE(p_error_message, error_message),
        next_attempt = COALESCE(p_next_attempt, next_attempt),
        delivered_at = COALESCE(p_delivered_at, delivered_at),
        attempt_count = CASE 
            WHEN p_status = 'sending' THEN attempt_count + 1 
            ELSE attempt_count 
        END,
        last_attempt = CASE 
            WHEN p_status = 'sending' THEN NOW() 
            ELSE last_attempt 
        END
    WHERE id = p_queue_id;
END;
$$ LANGUAGE plpgsql;

-- ----- Get attachments for email ----------------------------------------------

CREATE OR REPLACE FUNCTION get_email_attachments(p_email_id INTEGER)
RETURNS TABLE (
    file_name VARCHAR,
    file_path VARCHAR,
    content_type VARCHAR
)
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    RETURN QUERY
    SELECT 
        a.file_name,
        a.file_path,
        a.content_type
    FROM attachments a
    WHERE a.email_id = p_email_id;
END;
$$ LANGUAGE plpgsql;

-- ----- Get queue statistics --------------------------------------------------

CREATE OR REPLACE FUNCTION get_queue_stats()
RETURNS TABLE (
    status VARCHAR,
    count BIGINT
)
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    RETURN QUERY
    SELECT 
        oq.status,
        COUNT(*)::BIGINT
    FROM outbound_queue oq
    GROUP BY oq.status;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION get_pending_queue_count()
RETURNS BIGINT
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_count BIGINT;
BEGIN
    SELECT COUNT(*) INTO v_count
    FROM outbound_queue
    WHERE status IN ('pending', 'retry');
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

-- ----- Grant execute to mail_external_app -------------------------------------

GRANT EXECUTE ON FUNCTION get_pending_outbound_emails(TIMESTAMPTZ, TIMESTAMPTZ, INTEGER) TO mail_external_app;
GRANT EXECUTE ON FUNCTION get_email_for_delivery(INTEGER) TO mail_external_app;
GRANT EXECUTE ON FUNCTION get_email_cc_recipients(INTEGER, INTEGER, VARCHAR) TO mail_external_app;
GRANT EXECUTE ON FUNCTION get_user_email(INTEGER) TO mail_external_app;
GRANT EXECUTE ON FUNCTION update_queue_status(INTEGER, VARCHAR, TEXT, TIMESTAMPTZ, TIMESTAMPTZ) TO mail_external_app;
GRANT EXECUTE ON FUNCTION get_email_attachments(INTEGER) TO mail_external_app;
GRANT EXECUTE ON FUNCTION get_queue_stats() TO mail_external_app;
GRANT EXECUTE ON FUNCTION get_pending_queue_count() TO mail_external_app;

-- ----- Smoke check ------------------------------------------------------------

DO $$
BEGIN
    -- Verify functions exist
    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'get_pending_outbound_emails') THEN
        RAISE EXCEPTION 'Migration 005 failed: get_pending_outbound_emails not created';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'get_email_for_delivery') THEN
        RAISE EXCEPTION 'Migration 005 failed: get_email_for_delivery not created';
    END IF;
    RAISE NOTICE 'Migration 005: Queue processor functions created successfully';
END $$;
