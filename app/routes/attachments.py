import os
import uuid
import logging
from flask import Blueprint, request, jsonify, send_file
from app.utils.auth import token_required
from ..db import get_db_connection

bp = Blueprint('attachments', __name__)
logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx', 'zip'}
MAX_FILE_SIZE = 10 * 1024 * 1024

UPLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'uploads')

def allowed_file(filename):
	return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_unique_filename(filename):
	extension = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
	unique_name = str(uuid.uuid4())
	if extension:
		unique_name += '.' + extension
	return unique_name

@bp.route('/api/emails/<int:email_id>/attachments', methods=['POST'])
@token_required
def upload_attachment(email_id):
	"""
	Upload an attachment to an email
	---
	tags:
	  - Attachments
	security:
	  - Bearer: []
	consumes:
	  - multipart/form-data
	parameters:
	  - in: path
	    name: email_id
	    type: integer
	    required: true
	    description: Email ID
	  - in: formData
	    name: file
	    type: file
	    required: true
	    description: File to upload (max 10MB)
	responses:
	  201:
	    description: Attachment uploaded successfully
	    schema:
	      type: object
	      properties:
	        id:
	          type: integer
	        filename:
	          type: string
	  400:
	    description: No file uploaded or invalid file type
	  401:
	    description: Unauthorized
	  413:
	    description: File too large
	"""
	if 'file' not in request.files:
		return jsonify({'error': 'No file uploaded'}), 400
	
	file = request.files['file']
	
	if not file.filename:
		return jsonify({'error': 'No file selected'}), 400
	
	if not allowed_file(file.filename):
		return jsonify({'error': 'File type not allowed'}), 400
	
	if file.content_length and file.content_length > MAX_FILE_SIZE:
		return jsonify({'error': 'File too large (max 10MB)'}), 413
	
	# Verify user owns the email (via folder ownership)
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute(
		'SELECT e.id FROM emails e JOIN folders f ON e.folder_id = f.id WHERE e.id = %s AND f.user_id = %s',
		(email_id, request.current_user['id'])
	)
	email = cursor.fetchone()
	
	if not email:
		cursor.close()
		conn.close()
		return jsonify({'error': 'Email not found or unauthorized'}), 404
	
	unique_filename = get_unique_filename(file.filename)
	os.makedirs(UPLOADS_DIR, exist_ok=True)
	file_path = os.path.join(UPLOADS_DIR, unique_filename)
	file.save(file_path)
	file_size = os.path.getsize(file_path)
	
	cursor.execute(
		'INSERT INTO attachments (email_id, file_name, content_type, file_size, file_path) VALUES (%s, %s, %s, %s, %s) RETURNING id',
		(email_id, file.filename, file.content_type, file_size, file_path)
	)
	
	attachment_id = cursor.fetchone()['id']
	conn.commit()
	cursor.close()
	conn.close()
	
	return jsonify({'id': attachment_id, 'filename': file.filename}), 201

@bp.route('/api/emails/<int:email_id>/attachments', methods=['GET'])
@token_required
def list_attachments(email_id):
	"""
	List attachments for an email
	---
	tags:
	  - Attachments
	security:
	  - Bearer: []
	parameters:
	  - in: path
	    name: email_id
	    type: integer
	    required: true
	    description: Email ID
	responses:
	  200:
	    description: List of attachments
	    schema:
	      type: array
	      items:
	        type: object
	        properties:
	          id:
	            type: integer
	          file_name:
	            type: string
	          content_type:
	            type: string
	          file_size:
	            type: integer
	  401:
	    description: Unauthorized
	"""
	# Verify user owns the email (via folder ownership)
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute(
		'SELECT e.id FROM emails e JOIN folders f ON e.folder_id = f.id WHERE e.id = %s AND f.user_id = %s',
		(email_id, request.current_user['id'])
	)
	email = cursor.fetchone()
	
	if not email:
		cursor.close()
		conn.close()
		return jsonify({'error': 'Email not found or unauthorized'}), 404
	
	cursor.execute('SELECT id, email_id, file_name, content_type, file_size FROM attachments WHERE email_id = %s', (email_id,))
	attachments = cursor.fetchall()
	cursor.close()
	conn.close()
	
	return jsonify([dict(a) for a in attachments])

@bp.route('/api/attachments/<int:attachment_id>', methods=['GET'])
@token_required
def download_attachment(attachment_id):
	"""
	Download an attachment
	---
	tags:
	  - Attachments
	security:
	  - Bearer: []
	parameters:
	  - in: path
	    name: attachment_id
	    type: integer
	    required: true
	    description: Attachment ID
	produces:
	  - application/octet-stream
	responses:
	  200:
	    description: File download
	    content:
	      application/octet-stream:
	        schema:
	          type: string
	          format: binary
	  404:
	    description: Attachment not found
	  401:
	    description: Unauthorized
	"""
	conn = get_db_connection()
	cursor = conn.cursor()
	
	cursor.execute(
		'''SELECT a.file_path, a.file_name FROM attachments a
		   JOIN emails e ON a.email_id = e.id
		   JOIN folders f ON e.folder_id = f.id
		   WHERE a.id = %s AND f.user_id = %s''',
		(attachment_id, request.current_user['id'])
	)
	attachment = cursor.fetchone()
	cursor.close()
	conn.close()
	
	if not attachment:
		return jsonify({'error': 'Attachment not found'}), 404
	
	file_path = attachment['file_path']
	if not file_path or not os.path.exists(file_path):
		# Attachment exists in MIME raw_email but not on filesystem
		return jsonify({'error': 'Attachment data not available on filesystem'}), 404
	
	return send_file(file_path, as_attachment=True, download_name=attachment['file_name'])

@bp.route('/api/attachments/<int:attachment_id>', methods=['DELETE'])
@token_required
def delete_attachment_route(attachment_id):
	"""
	Delete an attachment
	---
	tags:
	  - Attachments
	security:
	  - Bearer: []
	parameters:
	  - in: path
	    name: attachment_id
	    type: integer
	    required: true
	    description: Attachment ID
	responses:
	  200:
	    description: Attachment deleted
	    schema:
	      type: object
	      properties:
	        status:
	          type: string
	  404:
	    description: Attachment not found
	  401:
	    description: Unauthorized
	"""
	conn = get_db_connection()
	cursor = conn.cursor()
	
	cursor.execute(
		'''SELECT a.file_path FROM attachments a
		   JOIN emails e ON a.email_id = e.id
		   JOIN folders f ON e.folder_id = f.id
		   WHERE a.id = %s AND f.user_id = %s''',
		(attachment_id, request.current_user['id'])
	)
	attachment = cursor.fetchone()
	
	if not attachment:
		cursor.close()
		conn.close()
		return jsonify({'error': 'Attachment not found'}), 404
	
	file_path = attachment['file_path']
	if file_path and os.path.exists(file_path):
		os.remove(file_path)
	
	cursor.execute('DELETE FROM attachments WHERE id = %s', (attachment_id,))
	conn.commit()
	cursor.close()
	conn.close()
	
	return jsonify({'status': 'deleted'})
