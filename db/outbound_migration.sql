-- Migration: Add outbound email delivery tables
-- Run this if your database was created before outbound support

-- Outbound email queue for external delivery
CREATE TABLE IF NOT EXISTS outbound_queue (
	id SERIAL PRIMARY KEY,
	email_id INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
	recipient_email VARCHAR(255) NOT NULL,
	recipient_domain VARCHAR(255) NOT NULL,
	status VARCHAR(20) NOT NULL DEFAULT 'pending',
	attempt_count INTEGER DEFAULT 0,
	last_attempt TIMESTAMP WITH TIME ZONE,
	next_attempt TIMESTAMP WITH TIME ZONE,
	error_message TEXT,
	delivered_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Delivery logs for tracking all attempts
CREATE TABLE IF NOT EXISTS delivery_logs (
	id SERIAL PRIMARY KEY,
	outbound_queue_id INTEGER REFERENCES outbound_queue(id) ON DELETE CASCADE,
	email_id INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
	recipient_email VARCHAR(255) NOT NULL,
	event_type VARCHAR(20) NOT NULL,
	smtp_response TEXT,
	error_message TEXT,
	remote_server VARCHAR(255),
	created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for outbound queue
CREATE INDEX IF NOT EXISTS idx_outbound_status ON outbound_queue(status);
CREATE INDEX IF NOT EXISTS idx_outbound_next_attempt ON outbound_queue(next_attempt);
CREATE INDEX IF NOT EXISTS idx_outbound_domain ON outbound_queue(recipient_domain);
CREATE INDEX IF NOT EXISTS idx_delivery_logs_email ON delivery_logs(email_id);
CREATE INDEX IF NOT EXISTS idx_delivery_logs_queue ON delivery_logs(outbound_queue_id);

-- Verify tables were created
SELECT 'outbound_queue table created' AS status WHERE EXISTS (
	SELECT 1 FROM information_schema.tables WHERE table_name = 'outbound_queue'
);

SELECT 'delivery_logs table created' AS status WHERE EXISTS (
	SELECT 1 FROM information_schema.tables WHERE table_name = 'delivery_logs'
);
