-- Migration: Add body_html column to emails table
-- This allows storing both plain text and HTML versions of email bodies

ALTER TABLE emails ADD COLUMN IF NOT EXISTS body_html TEXT;

-- Add index for HTML body searches (optional, for large deployments)
-- CREATE INDEX idx_emails_body_html ON emails USING gin(to_tsvector('english', body_html));
