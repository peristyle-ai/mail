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
	
	conn.commit()
	cursor.close()
	conn.close()
	print("Database initialized successfully!")

if __name__ == '__main__':
	init_db()
