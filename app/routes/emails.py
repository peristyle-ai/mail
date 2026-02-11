from flask import Blueprint, request, jsonify
from app.utils.auth import token_required
from ..db import get_db_connection

bp = Blueprint('emails', __name__)

@bp.route('/api/emails', methods=['GET'])
@token_required
def list_emails():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM emails WHERE user_id = %s ORDER BY created_at DESC', (request.current_user['id'],))
    emails = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify([dict(e) for e in emails])

@bp.route('/api/emails/<int:email_id>', methods=['GET'])
@token_required
def get_email(email_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM emails WHERE id = %s AND user_id = %s', (email_id, request.current_user['id']))
    email = cursor.fetchone()
    cursor.close()
    conn.close()
    if not email:
        return jsonify({'error': 'Email not found'}), 404
    return jsonify(dict(email))

@bp.route('/api/emails', methods=['POST'])
@token_required
def create_email():
    data = request.get_json()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO emails (user_id, to_email, subject, body, folder_id) VALUES (%s, %s, %s, %s, %s) RETURNING id',
        (request.current_user['id'], data.get('to'), data.get('subject'), data.get('body'), data.get('folder_id', 1))
    )
    email_id = cursor.fetchone()['id']
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'id': email_id}), 201

@bp.route('/api/emails/<int:email_id>/read', methods=['POST'])
@token_required
def mark_as_read(email_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE emails SET is_read = TRUE WHERE id = %s AND user_id = %s', (email_id, request.current_user['id']))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'status': 'read'})

@bp.route('/api/emails/<int:email_id>/star', methods=['POST'])
@token_required
def toggle_starred(email_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT is_starred FROM emails WHERE id = %s', (email_id,))
    email = cursor.fetchone()
    if not email:
        return jsonify({'error': 'Email not found'}), 404
    new_state = not email['is_starred']
    cursor.execute('UPDATE emails SET is_starred = %s WHERE id = %s', (new_state, email_id))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'is_starred': new_state})

@bp.route('/api/emails/<int:email_id>', methods=['DELETE'])
@token_required
def delete_email(email_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM emails WHERE id = %s AND user_id = %s', (email_id, request.current_user['id']))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'status': 'deleted'})

@bp.route('/api/emails/<int:email_id>/move', methods=['POST'])
@token_required
def move_email(email_id):
    data = request.get_json()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE emails SET folder_id = %s WHERE id = %s AND user_id = %s', (data['folder_id'], email_id, request.current_user['id']))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({'status': 'moved'})
