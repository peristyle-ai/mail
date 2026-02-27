-- Migration: Add body_html and raw_email columns to emails table
-- This allows storing both plain text and HTML versions of email bodies

ALTER TABLE emails ADD COLUMN IF NOT EXISTS body_html TEXT;
ALTER TABLE emails ADD COLUMN IF NOT EXISTS raw_email TEXT;

-- Add index for HTML body searches (optional, for large deployments)
-- CREATE INDEX idx_emails_body_html ON emails USING gin(to_tsvector('english', body_html));
