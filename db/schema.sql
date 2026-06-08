-- Users table
CREATE TABLE users (
	id SERIAL PRIMARY KEY,
	email VARCHAR(255) UNIQUE NOT NULL,
	password_hash VARCHAR(255) NOT NULL,
	name VARCHAR(255),
	is_local BOOLEAN DEFAULT TRUE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Folders table (Inbox, Sent, Drafts, Trash, custom folders)
CREATE TABLE folders (
	id SERIAL PRIMARY KEY,
	user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
	name VARCHAR(100) NOT NULL,
	parent_id INTEGER REFERENCES folders(id) ON DELETE CASCADE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
	UNIQUE(user_id, name)
);

-- Emails table
CREATE TABLE emails (
	id SERIAL PRIMARY KEY,
	sender_id INTEGER NOT NULL REFERENCES users(id),
	recipient_id INTEGER REFERENCES users(id),
	source_email_id INTEGER REFERENCES emails(id) ON DELETE SET NULL,
	folder_id INTEGER REFERENCES folders(id),
	subject VARCHAR(500),
	body TEXT,
	body_html TEXT,
	raw_email TEXT,
	headers TEXT,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
	is_read BOOLEAN DEFAULT FALSE,
	is_starred BOOLEAN DEFAULT FALSE
);

-- Email recipients (for multiple TO/CC/BCC)
CREATE TABLE email_recipients (
	id SERIAL PRIMARY KEY,
	email_id INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
	user_id INTEGER NOT NULL REFERENCES users(id),
	recipient_type VARCHAR(10) NOT NULL CHECK (recipient_type IN ('to', 'cc', 'bcc'))
);

-- Attachments table
CREATE TABLE attachments (
	id SERIAL PRIMARY KEY,
	email_id INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
	file_name VARCHAR(255) NOT NULL,
	content_type VARCHAR(255),
	file_path VARCHAR(500),
	file_size BIGINT,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Greylisting table for spam reduction
CREATE TABLE greylist (
	id SERIAL PRIMARY KEY,
	client_ip INET NOT NULL,
	sender VARCHAR(255) NOT NULL,
	recipient VARCHAR(255) NOT NULL,
	first_seen TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
	retry_count INTEGER DEFAULT 0,
	whitelisted BOOLEAN DEFAULT FALSE,
	UNIQUE(client_ip, sender, recipient)
);

-- Rate limit violations tracking
CREATE TABLE rate_limit_violations (
	id SERIAL PRIMARY KEY,
	client_ip INET NOT NULL,
	violation_type VARCHAR(50) NOT NULL,
	count INTEGER DEFAULT 1,
	timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX idx_emails_sender ON emails(sender_id);
CREATE INDEX idx_emails_folder ON emails(folder_id);
CREATE INDEX idx_emails_source_email_id ON emails(source_email_id);
CREATE INDEX idx_emails_created ON emails(created_at);
CREATE INDEX idx_recipients_user ON email_recipients(user_id);
CREATE INDEX idx_attachments_email ON attachments(email_id);
CREATE INDEX idx_greylist_ip ON greylist(client_ip);
CREATE INDEX idx_greylist_whitelisted ON greylist(whitelisted);
CREATE INDEX idx_greylist_sender ON greylist(sender);
CREATE INDEX idx_rate_violations_ip ON rate_limit_violations(client_ip);
CREATE INDEX idx_rate_violations_time ON rate_limit_violations(timestamp);

-- ============================================
-- IP Blacklist Table (Phase 1)
-- ============================================

-- IP Blacklist table (immediate rejection)
CREATE TABLE ip_blacklist (
	id SERIAL PRIMARY KEY,
	ip_address INET NOT NULL UNIQUE,
	reason VARCHAR(255),
	source VARCHAR(50), -- 'manual', 'auto_spf_fail', 'auto_rate_limit', 'dnsbl'
	expires_at TIMESTAMP WITH TIME ZONE,  -- NULL = permanent
	hit_count INTEGER DEFAULT 0,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
	created_by INTEGER REFERENCES users(id) ON DELETE SET NULL  -- Track who added it
);

-- Indexes for blacklist
CREATE INDEX idx_ip_blacklist_address ON ip_blacklist(ip_address);
CREATE INDEX idx_ip_blacklist_expires ON ip_blacklist(expires_at);

-- ============================================
-- Sender Blocklist Table
-- ============================================

-- Sender Blocklist table (blocks specific emails or entire domains)
CREATE TABLE sender_blocklist (
	id SERIAL PRIMARY KEY,
	email VARCHAR(255),
	domain VARCHAR(255),
	source VARCHAR(50) DEFAULT 'manual',
	blocked_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
	blocked_by INTEGER REFERENCES users(id),
	notes TEXT,
	CONSTRAINT check_block_target CHECK (email IS NOT NULL OR domain IS NOT NULL)
);

CREATE UNIQUE INDEX idx_sender_blocklist_email ON sender_blocklist(email) WHERE email IS NOT NULL;
CREATE UNIQUE INDEX idx_sender_blocklist_domain ON sender_blocklist(domain) WHERE email IS NULL AND domain IS NOT NULL;

-- ============================================
-- Outbound Email Delivery Tables
-- ============================================

-- Outbound email queue for external delivery
CREATE TABLE outbound_queue (
	id SERIAL PRIMARY KEY,
	email_id INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
	recipient_email VARCHAR(255) NOT NULL,
	recipient_domain VARCHAR(255) NOT NULL,
	status VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending, sending, sent, bounced, failed
	attempt_count INTEGER DEFAULT 0,
	last_attempt TIMESTAMP WITH TIME ZONE,
	next_attempt TIMESTAMP WITH TIME ZONE,
	error_message TEXT,
	delivered_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Delivery logs for tracking all attempts
CREATE TABLE delivery_logs (
	id SERIAL PRIMARY KEY,
	outbound_queue_id INTEGER REFERENCES outbound_queue(id) ON DELETE CASCADE,
	email_id INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
	recipient_email VARCHAR(255) NOT NULL,
	event_type VARCHAR(20) NOT NULL, -- attempt, success, bounce, failure
	smtp_response TEXT,
	error_message TEXT,
	remote_server VARCHAR(255),
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for outbound queue
CREATE INDEX idx_outbound_status ON outbound_queue(status);
CREATE INDEX idx_outbound_next_attempt ON outbound_queue(next_attempt);
CREATE INDEX idx_outbound_domain ON outbound_queue(recipient_domain);
CREATE INDEX idx_delivery_logs_email ON delivery_logs(email_id);

-- Per-domain outbound relay configuration
CREATE TABLE domains (
	id SERIAL PRIMARY KEY,
	domain VARCHAR(255) NOT NULL UNIQUE,
	relay_provider VARCHAR(50),
	relay_host VARCHAR(255),
	relay_port INTEGER DEFAULT 2525,
	relay_username VARCHAR(255),
	relay_password_encrypted VARCHAR(500),
	relay_from_address VARCHAR(255),
	relay_verified BOOLEAN DEFAULT FALSE,
	relay_verified_at TIMESTAMP WITH TIME ZONE,
	webhook_secret VARCHAR(500),
	webhook_secret_updated_at TIMESTAMP WITH TIME ZONE,
	spf_verified BOOLEAN DEFAULT FALSE,
	dkim_verified BOOLEAN DEFAULT FALSE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_domains_domain ON domains(domain);
CREATE INDEX idx_domains_relay_provider ON domains(relay_provider);
CREATE INDEX idx_domains_relay_verified ON domains(relay_verified);

-- Major email provider domains (greylist whitelist)
CREATE TABLE major_providers (
	id SERIAL PRIMARY KEY,
	domain VARCHAR(255) UNIQUE NOT NULL,
	description VARCHAR(255),
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_delivery_logs_queue ON delivery_logs(outbound_queue_id);
