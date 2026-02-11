-- Users table
CREATE TABLE users (
	id SERIAL PRIMARY KEY,
	email VARCHAR(255) UNIQUE NOT NULL,
	password_hash VARCHAR(255) NOT NULL,
	name VARCHAR(255),
	created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
	updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Folders table (Inbox, Sent, Drafts, Trash, custom folders)
CREATE TABLE folders (
	id SERIAL PRIMARY KEY,
	user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
	name VARCHAR(100) NOT NULL,
	parent_id INTEGER REFERENCES folders(id) ON DELETE CASCADE,
	created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
	UNIQUE(user_id, name)
);

-- Emails table
CREATE TABLE emails (
	id SERIAL PRIMARY KEY,
	sender_id INTEGER NOT NULL REFERENCES users(id),
	folder_id INTEGER REFERENCES folders(id),
	subject VARCHAR(500),
	body TEXT,
	headers TEXT,
	created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
	user_id INTEGER NOT NULL REFERENCES users(id),
	filename VARCHAR(255) NOT NULL,
	content_type VARCHAR(255),
	file_path VARCHAR(500),
	file_size BIGINT,
	created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX idx_emails_sender ON emails(sender_id);
CREATE INDEX idx_emails_folder ON emails(folder_id);
CREATE INDEX idx_emails_created ON emails(created_at);
CREATE INDEX idx_recipients_user ON email_recipients(user_id);
CREATE INDEX idx_attachments_email ON attachments(email_id);
