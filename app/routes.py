from flask import Blueprint, request, jsonify
from .db import get_db_connection

bp = Blueprint('routes', __name__)

@bp.route('/health', methods=['GET'])
def health():
	return jsonify({'status': 'ok'})

@bp.route('/api/emails', methods=['GET'])
def get_emails():
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute('SELECT * FROM emails ORDER BY created_at DESC')
	emails = cursor.fetchall()
	cursor.close()
	conn.close()
	return jsonify([dict(e) for e in emails])

@bp.route('/api/emails/<int:email_id>', methods=['GET'])
def get_email(email_id):
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute('SELECT * FROM emails WHERE id = %s', (email_id,))
	email = cursor.fetchone()
	cursor.close()
	conn.close()
	if not email:
		return jsonify({'error': 'Email not found'}), 404
	return jsonify(dict(email))

@bp.route('/api/emails', methods=['POST'])
def create_email():
	data = request.get_json()
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute(
		'INSERT INTO emails (sender_id, subject, body, headers, folder_id) VALUES (%s, %s, %s, %s, %s) RETURNING id',
		(data['sender_id'], data['subject'], data['body'], data.get('headers'), data.get('folder_id'))
	)
	email_id = int(cursor.fetchone()[0])
	conn.commit()
	cursor.close()
	conn.close()
	return jsonify({'id': email_id}), 201

@bp.route('/api/folders', methods=['GET'])
def get_folders():
	user_id = request.args.get('user_id')
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute('SELECT * FROM folders WHERE user_id = %s ORDER BY name', (user_id,))
	folders = cursor.fetchall()
	cursor.close()
	conn.close()
	return jsonify([dict(f) for f in folders])

@bp.route('/api/folders', methods=['POST'])
def create_folder():
	data = request.get_json()
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute('INSERT INTO folders (user_id, name, parent_id) VALUES (%s, %s, %s) RETURNING id', (data['user_id'], data['name'], data.get('parent_id')))
	folder_id = int(cursor.fetchone()[0])
	conn.commit()
	cursor.close()
	conn.close()
	return jsonify({'id': folder_id}), 201
