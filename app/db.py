import psycopg2
from psycopg2.extras import RealDictCursor
import os
from dotenv import load_dotenv

load_dotenv()

def get_db_connection():
	conn = psycopg2.connect(os.getenv('DATABASE_URL'), cursor_factory=RealDictCursor)
	return conn
