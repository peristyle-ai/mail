import os
from flask import Blueprint, request, jsonify, send_file
from app.utils.auth import token_required
from .db import get_db_connection

bp = Blueprint('attachments', __name__)

ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx', 'zip'}
MAX_FILE_SIZE = 10 * 1024 * 1024

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_unique_filename(filename):
    import uuid
    extension = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    unique_name = str(uuid.uuid4())
    if extension:
        unique_name += '.' + extension
    return unique_name

@bp.route('/api/emails/<int:email_id>/attachments', methods=['POST'])
@token_required
def upload_attachment(email_id):
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    
    file = request.files['file']
    
    if not file.filename:
        return jsonify({'error': 'No file selected'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': 'File type not allowed'}), 400
    
    if file.content_length > MAX_FILE_SIZE:
        return jsonify({'error': 'File too large (max 10MB)'}), 413
    
    unique_filename = get_unique_filename(file.filename)
    file_path = f"uploads/{unique_filename}"
    file.save(file_path)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        'INSERT INTO attachments (email_id, filename, content_type, file_path, file_size, user_id) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id',
        (email_id, file.filename, file.content_type, file_path, file.content_length, request.current_user['id'])
    )
    
    attachment_id = cursor.fetchone()['id']
    conn.commit()
    cursor.close()
    conn.close()
    
    return jsonify({'id': attachment_id, 'filename': file.filename}), 201

@bp.route('/api/emails/<int:email_id>/attachments', methods=['GET'])
@token_required
def list_attachments(email_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM attachments WHERE email_id = %s', (email_id,))
    attachments = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return jsonify([dict(a) for a in attachments])

@bp.route('/api/attachments/<int:attachment_id>', methods=['GET'])
@token_required
def download_attachment(attachment_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT file_path FROM attachments WHERE id = %s AND user_id = %s', (attachment_id, request.current_user['id']))
    attachment = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if not attachment or not os.path.exists(attachment['file_path']):
        return jsonify({'error': 'Attachment not found'}), 404
    
    return send_file(attachment['file_path'], as_attachment=True)

@bp.route('/api/attachments/<int:attachment_id>', methods=['DELETE'])
@token_required
def delete_attachment_route(attachment_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT file_path FROM attachments WHERE id = %s AND user_id = %s', (attachment_id, request.current_user['id']))
    attachment = cursor.fetchone()
    
    if not attachment:
        return jsonify({'error': 'Attachment not found'}), 404
    
    file_path = attachment['file_path']
    if os.path.exists(file_path):
        os.remove(file_path)
    
    cursor.execute('DELETE FROM attachments WHERE id = %s', (attachment_id,))
    conn.commit()
    cursor.close()
    conn.close()
    
    return jsonify({'status': 'deleted'})
