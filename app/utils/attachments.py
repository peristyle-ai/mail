import os
import uuid
from flask import request, jsonify
from werkzeug.utils import secure_filename
from .db import get_db_connection

UPLOAD_FOLDER = 'uploads'
MAX_FILE_SIZE = 10 * 1024 * 1024

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx', 'zip'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_unique_filename(filename):
    extension = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    unique_name = str(uuid.uuid4())
    if extension:
        unique_name += '.' + extension
    return unique_name

def save_attachment(attachment_data, email_id, user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        'INSERT INTO attachments (email_id, filename, content_type, file_path, file_size, user_id) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id',
        (email_id, attachment_data['filename'], attachment_data['content_type'], attachment_data['file_path'], attachment_data['file_size'], user_id)
    )
    
    attachment_id = cursor.fetchone()['id']
    conn.commit()
    cursor.close()
    conn.close()
    
    return attachment_id

def get_email_attachments(email_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM attachments WHERE email_id = %s', (email_id,))
    attachments = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return [dict(a) for a in attachments]

def delete_attachment(attachment_id, user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT file_path FROM attachments WHERE id = %s AND user_id = %s', (attachment_id, user_id))
    attachment = cursor.fetchone()
    
    if not attachment:
        return False
    
    file_path = attachment['file_path']
    if os.path.exists(file_path):
        os.remove(file_path)
    
    cursor.execute('DELETE FROM attachments WHERE id = %s', (attachment_id,))
    conn.commit()
    cursor.close()
    conn.close()
    
    return True

def get_attachment_path(attachment_id, user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT file_path FROM attachments WHERE id = %s AND user_id = %s', (attachment_id, user_id))
    attachment = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if attachment:
        return attachment['file_path']
    return None