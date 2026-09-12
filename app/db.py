import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv

load_dotenv()

def get_db_connection():
	conn = psycopg2.connect(os.getenv('DATABASE_URL'), cursor_factory=RealDictCursor)
	return conn


def ensure_attachments_schema():
	"""Align attachment column names with the current application code."""
	lock_id = 872342
	conn = get_db_connection()
	cursor = conn.cursor()

	try:
		cursor.execute('SELECT pg_advisory_lock(%s)', (lock_id,))
		cursor.execute(
			'''
			SELECT 1
			FROM information_schema.columns
			WHERE table_schema = 'public'
			AND table_name = 'attachments'
			AND column_name = 'filename'
			'''
		)
		has_old_filename = cursor.fetchone() is not None
		cursor.execute(
			'''
			SELECT 1
			FROM information_schema.columns
			WHERE table_schema = 'public'
			AND table_name = 'attachments'
			AND column_name = 'file_name'
			'''
		)
		has_file_name = cursor.fetchone() is not None

		if has_old_filename and not has_file_name:
			cursor.execute('ALTER TABLE attachments RENAME COLUMN filename TO file_name')

		cursor.execute('ALTER TABLE attachments ADD COLUMN IF NOT EXISTS file_name VARCHAR(255)')
		cursor.execute('ALTER TABLE attachments ADD COLUMN IF NOT EXISTS file_path VARCHAR(500)')
		conn.commit()
	finally:
		try:
			cursor.execute('SELECT pg_advisory_unlock(%s)', (lock_id,))
		except Exception:
			conn.rollback()
		cursor.close()
		conn.close()


def ensure_email_copy_schema():
	"""Add linkage from local inbox copies back to the sent email."""
	lock_id = 872344
	conn = get_db_connection()
	cursor = conn.cursor()

	try:
		cursor.execute('SELECT pg_advisory_lock(%s)', (lock_id,))
		cursor.execute('ALTER TABLE emails ADD COLUMN IF NOT EXISTS source_email_id INTEGER REFERENCES emails(id) ON DELETE SET NULL')
		cursor.execute('CREATE INDEX IF NOT EXISTS idx_emails_source_email_id ON emails(source_email_id)')
		conn.commit()
	finally:
		try:
			cursor.execute('SELECT pg_advisory_unlock(%s)', (lock_id,))
		except Exception:
			conn.rollback()
		cursor.close()
		conn.close()


def ensure_domains_table():
	"""Create the domains table used for outbound relay configuration."""
	lock_id = 872341
	conn = get_db_connection()
	cursor = conn.cursor()

	try:
		cursor.execute('SELECT pg_advisory_lock(%s)', (lock_id,))
		cursor.execute(
			'''
			CREATE TABLE IF NOT EXISTS domains (
				id SERIAL PRIMARY KEY,
				domain VARCHAR(255) NOT NULL,
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
			)
			'''
		)
		cursor.execute('ALTER TABLE domains ADD COLUMN IF NOT EXISTS relay_provider VARCHAR(50)')
		cursor.execute('ALTER TABLE domains ADD COLUMN IF NOT EXISTS relay_host VARCHAR(255)')
		cursor.execute('ALTER TABLE domains ADD COLUMN IF NOT EXISTS relay_port INTEGER DEFAULT 2525')
		cursor.execute('ALTER TABLE domains ADD COLUMN IF NOT EXISTS relay_username VARCHAR(255)')
		cursor.execute('ALTER TABLE domains ADD COLUMN IF NOT EXISTS relay_password_encrypted VARCHAR(500)')
		cursor.execute('ALTER TABLE domains ADD COLUMN IF NOT EXISTS relay_from_address VARCHAR(255)')
		cursor.execute('ALTER TABLE domains ADD COLUMN IF NOT EXISTS relay_verified BOOLEAN DEFAULT FALSE')
		cursor.execute('ALTER TABLE domains ADD COLUMN IF NOT EXISTS relay_verified_at TIMESTAMP WITH TIME ZONE')
		cursor.execute('ALTER TABLE domains ADD COLUMN IF NOT EXISTS webhook_secret VARCHAR(500)')
		cursor.execute('ALTER TABLE domains ADD COLUMN IF NOT EXISTS webhook_secret_updated_at TIMESTAMP WITH TIME ZONE')
		cursor.execute('ALTER TABLE domains ADD COLUMN IF NOT EXISTS spf_verified BOOLEAN DEFAULT FALSE')
		cursor.execute('ALTER TABLE domains ADD COLUMN IF NOT EXISTS dkim_verified BOOLEAN DEFAULT FALSE')
		cursor.execute('ALTER TABLE domains ADD COLUMN IF NOT EXISTS created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP')
		cursor.execute('ALTER TABLE domains ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP')
		cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_domains_domain ON domains(domain)')
		cursor.execute('CREATE INDEX IF NOT EXISTS idx_domains_relay_provider ON domains(relay_provider)')
		cursor.execute('CREATE INDEX IF NOT EXISTS idx_domains_relay_verified ON domains(relay_verified)')
		conn.commit()
	finally:
		try:
			cursor.execute('SELECT pg_advisory_unlock(%s)', (lock_id,))
		except Exception:
			conn.rollback()
		cursor.close()
		conn.close()


def get_seed_domains():
	"""Return the local domains that should exist in the domains table."""
	seed_domains = {
		'example.com.au',
		'mailrelay.com',
		'example.ai',
		'example.ai',
		'example.ai',
	}

	env_domains = os.getenv('DOMAINS', '')
	for value in env_domains.split(','):
		value = value.strip().lower()
		if value:
			seed_domains.add(value)

	return sorted(seed_domains)


def seed_local_domains():
	"""Ensure local domains exist and seed webhook secrets when appropriate."""
	ensure_domains_table()
	lock_id = 872343
	conn = get_db_connection()
	cursor = conn.cursor()

	try:
		cursor.execute('SELECT pg_advisory_lock(%s)', (lock_id,))
		for domain in get_seed_domains():
			cursor.execute(
				'''INSERT INTO domains (domain)
				   VALUES (%s)
				   ON CONFLICT (domain) DO NOTHING''',
				(domain,)
			)

		webhook_secret = os.getenv('SMTP2GO_WEBHOOK_SECRET', '').strip()
		if webhook_secret and os.getenv('TESTING') != 'true':
			from app.utils.webhooks import hash_webhook_secret

			secret_hash = hash_webhook_secret(webhook_secret)
			cursor.execute(
				'''UPDATE domains
				   SET webhook_secret = %s,
				       webhook_secret_updated_at = CURRENT_TIMESTAMP,
				       updated_at = CURRENT_TIMESTAMP
				   WHERE domain = ANY(%s)
				   AND webhook_secret IS NULL''',
				(secret_hash, list(get_seed_domains()))
			)

		conn.commit()
	finally:
		try:
			cursor.execute('SELECT pg_advisory_unlock(%s)', (lock_id,))
		except Exception:
			conn.rollback()
		cursor.close()
		conn.close()
