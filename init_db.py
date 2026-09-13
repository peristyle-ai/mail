import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')

def init_db():
	conn = psycopg2.connect(DATABASE_URL)
	cursor = conn.cursor()
	
	with open('db/schema.sql', 'r') as f:
		schema = f.read()
		cursor.execute(schema)
	
	with open('db/add_body_html.sql', 'r') as f:
		migration = f.read()
		cursor.execute(migration)
	
	with open('db/add_sender_blocklist.sql', 'r') as f:
		migration = f.read()
		cursor.execute(migration)
	
	# Rate limiting table (database-backed, survives restarts)
	cursor.execute('''
		CREATE TABLE IF NOT EXISTS rate_limit_attempts (
			id SERIAL PRIMARY KEY,
			key VARCHAR(500) NOT NULL,
			attempted_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
		)
	''')
	cursor.execute('''
		CREATE INDEX IF NOT EXISTS idx_rate_limit_attempts_key
		ON rate_limit_attempts(key)
	''')
	cursor.execute('''
		CREATE INDEX IF NOT EXISTS idx_rate_limit_attempts_time
		ON rate_limit_attempts(attempted_at)
	''')
	
	conn.commit()
	cursor.close()
	conn.close()
	print("Database initialized successfully!")

if __name__ == '__main__':
	init_db()
