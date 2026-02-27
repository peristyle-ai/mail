-- Migration: Add sender blocklist table
-- Blocks specific email addresses or entire domains from sending emails

CREATE TABLE IF NOT EXISTS sender_blocklist (
	id SERIAL PRIMARY KEY,
	email VARCHAR(255),
	domain VARCHAR(255),
	source VARCHAR(50) DEFAULT 'manual',
	blocked_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
	blocked_by INTEGER REFERENCES users(id),
	notes TEXT,
	CONSTRAINT check_block_target CHECK (email IS NOT NULL OR domain IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sender_blocklist_email ON sender_blocklist(email) WHERE email IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_sender_blocklist_domain ON sender_blocklist(domain) WHERE email IS NULL AND domain IS NOT NULL;
