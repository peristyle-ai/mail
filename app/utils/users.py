from datetime import datetime
from .db import get_db_connection

def get_user_by_email(email):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE email = %s', (email,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    return user

def create_user(email, password, name):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO users (email, password_hash, name, created_at) VALUES (%s, %s, %s, %s) RETURNING id, email',
                   (email, password, name, datetime.utcnow()))
    user = cursor.fetchone()
    conn.commit()
    cursor.close()
    conn.close()
    return user
