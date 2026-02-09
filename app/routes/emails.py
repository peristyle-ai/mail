from flask import Blueprint, request, jsonify
from .db import get_db_connection

bp = Blueprint('emails', __name__)

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

@bp.route('/api/emails/<int:email_id>/read', methods=['POST'])
def mark_as_read(email_id):
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute('UPDATE emails SET is_read = TRUE WHERE id = %s', (email_id,))
	conn.commit()
	cursor.close()
	conn.close()
	return jsonify({'status': 'marked as read'})

@bp.route('/api/emails/<int:email_id>/star', methods=['POST'])
def mark_as_starred(email_id):
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute('UPDATE emails SET is_starred = NOT is_starred WHERE id = %s RETURNING is_starred', (email_id,))
	is_starred = cursor.fetchone()['is_starred']
	conn.commit()
	cursor.close()
	conn.close()
	return jsonify({'is_starred': is_starred})

@bp.route('/api/emails/<int:email_id>', methods=['DELETE'])
def delete_email(email_id):
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute('DELETE FROM emails WHERE id = %s', (email_id,))
	conn.commit()
	cursor.close()
	conn.close()
	return jsonify({'status': 'deleted'})

@bp.route('/api/emails/<int:email_id>/move', methods=['POST'])
def move_email(email_id):
	data = request.get_json()
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute('UPDATE emails SET folder_id = %s WHERE id = %s', (data['folder_id'], email_id))
	conn.commit()
	cursor.close()
	conn.close()
	return jsonify({'status': 'moved'})
