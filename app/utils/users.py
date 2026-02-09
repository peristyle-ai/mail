from app.db import get_db_connection

def get_user_by_email(email):
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute('SELECT * FROM users WHERE email = %s', (email,))
	user = cursor.fetchone()
	cursor.close()
	conn.close()
	return user

def create_user(email, password_hash, name=None):
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute('INSERT INTO users (email, password_hash, name) VALUES (%s, %s, %s) RETURNING id', (email, password_hash, name))
	user_id = cursor.fetchone()['id']
	conn.commit()
	cursor.close()
	conn.close()
	return user_id
