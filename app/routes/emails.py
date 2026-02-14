from flask import Blueprint, request, jsonify
from app.utils.auth import token_required
from ..db import get_db_connection
import logging

bp = Blueprint('emails', __name__)
logger = logging.getLogger(__name__)

@bp.route('/api/emails', methods=['GET'])
@token_required
def list_emails():
	"""
	List all emails for authenticated user
	---
	tags:
	  - Emails
	security:
	  - Bearer: []
	responses:
	  200:
	    description: List of emails
	    schema:
	      type: array
	      items:
	        type: object
	        properties:
	          id:
	            type: integer
	          subject:
	            type: string
	          body:
	            type: string
	          is_read:
	            type: boolean
	          is_starred:
	            type: boolean
	          created_at:
	            type: string
	  401:
	    description: Unauthorized - invalid or missing token
	"""
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute('SELECT * FROM emails WHERE sender_id = %s ORDER BY created_at DESC', (request.current_user['id'],))
	emails = cursor.fetchall()
	cursor.close()
	conn.close()
	return jsonify([dict(e) for e in emails])

@bp.route('/api/emails/<int:email_id>', methods=['GET'])
@token_required
def get_email(email_id):
	"""
	Get a specific email by ID
	---
	tags:
	  - Emails
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
	    description: Email details
	    schema:
	      type: object
	  404:
	    description: Email not found
	  401:
	    description: Unauthorized
	"""
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute('SELECT * FROM emails WHERE id = %s AND sender_id = %s', (email_id, request.current_user['id']))
	email = cursor.fetchone()
	cursor.close()
	conn.close()
	if not email:
		return jsonify({'error': 'Email not found'}), 404
	return jsonify(dict(email))

@bp.route('/api/emails', methods=['POST'])
@token_required
def create_email():
	"""
	Create a new email
	---
	tags:
	  - Emails
	security:
	  - Bearer: []
	parameters:
	  - in: body
	    name: body
	    schema:
	      type: object
	      required:
	        - to
	      properties:
	        to:
	          type: string
	          description: Recipient email address
	        subject:
	          type: string
	          description: Email subject
	        body:
	          type: string
	          description: Email body
	        folder_id:
	          type: integer
	          description: Folder ID to store email in
	responses:
	  201:
	    description: Email created successfully
	    schema:
	      type: object
	      properties:
	        id:
	          type: integer
	  401:
	    description: Unauthorized
	"""
	data = request.get_json()
	conn = get_db_connection()
	cursor = conn.cursor()
	
	# Get sender's email
	cursor.execute('SELECT email FROM users WHERE id = %s', (request.current_user['id'],))
	sender_row = cursor.fetchone()
	if not sender_row:
		cursor.close()
		conn.close()
		return jsonify({'error': 'Sender not found'}), 400
	from_address = sender_row['email']
	
	# Handle recipients
	recipients = data.get('to')
	local_recipients = []
	external_recipients = []
	
	if recipients:
		if isinstance(recipients, str):
			recipients = [recipients]
		for recipient_email in recipients:
			cursor.execute('SELECT id FROM users WHERE email = %s', (recipient_email,))
			recipient_user = cursor.fetchone()
			if recipient_user:
				local_recipients.append((recipient_email, recipient_user['id']))
			else:
				external_recipients.append(recipient_email)
	
	# For external-only emails, use queue_outbound_email directly
	# This creates email in Sent folder and queues for delivery
	if external_recipients and not local_recipients:
		cursor.close()
		conn.close()
		
		from email.message import EmailMessage as EM
		from smtp_server.outbound.storage import queue_outbound_email
		
		msg = EM()
		msg['Subject'] = data.get('subject', '')
		msg['From'] = from_address
		if external_recipients:
			msg['To'] = ', '.join(external_recipients)
		msg.set_content(data.get('body', ''))
		
		try:
			email_id, queue_ids = queue_outbound_email(
				sender_id=request.current_user['id'],
				from_address=from_address,
				to_addresses=external_recipients,
				subject=data.get('subject', ''),
				body=data.get('body', ''),
				message=msg,
				headers=dict(msg.items())
			)
			return jsonify({'id': email_id, 'queued': len(queue_ids) > 0}), 201
		except Exception as e:
			logger.error(f"Error queueing outbound email: {e}")
			return jsonify({'error': str(e)}), 500
	
	# For local recipients (or mixed), create email normally
	# Get or validate folder_id
	folder_id = data.get('folder_id')
	if not folder_id:
		cursor.execute(
			'SELECT id FROM folders WHERE user_id = %s AND name = %s',
			(request.current_user['id'], 'Inbox')
		)
		folder = cursor.fetchone()
		if folder:
			folder_id = folder['id']
		else:
			cursor.execute(
				'INSERT INTO folders (user_id, name) VALUES (%s, %s) RETURNING id',
				(request.current_user['id'], 'Inbox')
			)
			folder_id = cursor.fetchone()['id']
	
	cursor.execute(
		'INSERT INTO emails (sender_id, subject, body, folder_id) VALUES (%s, %s, %s, %s) RETURNING id',
		(request.current_user['id'], data.get('subject'), data.get('body'), folder_id)
	)
	email_id = cursor.fetchone()['id']
	
	# Add local recipients
	for recipient_email, recipient_id in local_recipients:
		cursor.execute(
			'INSERT INTO email_recipients (email_id, user_id, recipient_type) VALUES (%s, %s, %s)',
			(email_id, recipient_id, 'to')
		)
	
	conn.commit()
	cursor.close()
	conn.close()
	
	# Queue external recipients if any
	if external_recipients:
		from email.message import EmailMessage as EM
		from smtp_server.outbound.storage import queue_outbound_email
		
		msg = EM()
		msg['Subject'] = data.get('subject', '')
		msg['From'] = from_address
		msg['To'] = ', '.join(external_recipients)
		msg.set_content(data.get('body', ''))
		
		try:
			_, queue_ids = queue_outbound_email(
				sender_id=request.current_user['id'],
				from_address=from_address,
				to_addresses=external_recipients,
				subject=data.get('subject', ''),
				body=data.get('body', ''),
				message=msg,
				headers=dict(msg.items())
			)
		except Exception as e:
			logger.error(f"Error queueing outbound email: {e}")
	
	return jsonify({'id': email_id}), 201

@bp.route('/api/emails/<int:email_id>/read', methods=['POST'])
@token_required
def mark_as_read(email_id):
	"""
	Mark an email as read
	---
	tags:
	  - Emails
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
	    description: Email marked as read
	    schema:
	      type: object
	      properties:
	        status:
	          type: string
	  401:
	    description: Unauthorized
	"""
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute('UPDATE emails SET is_read = TRUE WHERE id = %s AND sender_id = %s', (email_id, request.current_user['id']))
	conn.commit()
	cursor.close()
	conn.close()
	return jsonify({'status': 'read'})

@bp.route('/api/emails/<int:email_id>/star', methods=['POST'])
@token_required
def toggle_starred(email_id):
	"""
	Toggle starred status of an email
	---
	tags:
	  - Emails
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
	    description: Starred status toggled
	    schema:
	      type: object
	      properties:
	        is_starred:
	          type: boolean
	  404:
	    description: Email not found
	  401:
	    description: Unauthorized
	"""
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute('SELECT is_starred FROM emails WHERE id = %s AND sender_id = %s', (email_id, request.current_user['id']))
	email = cursor.fetchone()
	if not email:
		return jsonify({'error': 'Email not found'}), 404
	new_state = not email['is_starred']
	cursor.execute('UPDATE emails SET is_starred = %s WHERE id = %s AND sender_id = %s', (new_state, email_id, request.current_user['id']))
	conn.commit()
	cursor.close()
	conn.close()
	return jsonify({'is_starred': new_state})

@bp.route('/api/emails/<int:email_id>', methods=['DELETE'])
@token_required
def delete_email(email_id):
	"""
	Delete an email
	---
	tags:
	  - Emails
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
	    description: Email deleted
	    schema:
	      type: object
	      properties:
	        status:
	          type: string
	  401:
	    description: Unauthorized
	"""
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute('DELETE FROM emails WHERE id = %s AND sender_id = %s', (email_id, request.current_user['id']))
	conn.commit()
	cursor.close()
	conn.close()
	return jsonify({'status': 'deleted'})

@bp.route('/api/emails/<int:email_id>/move', methods=['POST'])
@token_required
def move_email(email_id):
	"""
	Move an email to a different folder
	---
	tags:
	  - Emails
	security:
	  - Bearer: []
	parameters:
	  - in: path
	    name: email_id
	    type: integer
	    required: true
	    description: Email ID
	  - in: body
	    name: body
	    schema:
	      type: object
	      required:
	        - folder_id
	      properties:
	        folder_id:
	          type: integer
	          description: Target folder ID
	responses:
	  200:
	    description: Email moved successfully
	    schema:
	      type: object
	      properties:
	        status:
	          type: string
	  401:
	    description: Unauthorized
	"""
	data = request.get_json()
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute('UPDATE emails SET folder_id = %s WHERE id = %s AND sender_id = %s', (data['folder_id'], email_id, request.current_user['id']))
	conn.commit()
	cursor.close()
	conn.close()
	return jsonify({'status': 'moved'})
