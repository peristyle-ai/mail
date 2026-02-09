from flask import request, jsonify
from app.db import get_db_connection

def get_folders(user_id):
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute('SELECT * FROM folders WHERE user_id = %s ORDER BY name', (user_id,))
	folders = cursor.fetchall()
	cursor.close()
	conn.close()
	return [dict(f) for f in folders]

def get_folder_by_name(user_id, name):
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute('SELECT * FROM folders WHERE user_id = %s AND name = %s', (user_id, name))
	folder = cursor.fetchone()
	cursor.close()
	conn.close()
	return folder

def create_folder(user_id, name, parent_id=None):
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute('INSERT INTO folders (user_id, name, parent_id) VALUES (%s, %s, %s) RETURNING id', (user_id, name, parent_id))
	folder_id = cursor.fetchone()['id']
	conn.commit()
	cursor.close()
	conn.close()
	return folder_id
