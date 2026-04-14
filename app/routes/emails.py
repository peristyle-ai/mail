from flask import Blueprint, request, jsonify
from app.utils.auth import token_required
from ..db import get_db_connection
import logging
from email import message_from_string
from email.message import EmailMessage
from email.policy import default

bp = Blueprint('emails', __name__)
logger = logging.getLogger(__name__)


def format_email_response(email_dict):
	"""Format email dict for API response, mapping body_html to html and adding email addresses."""
	result = dict(email_dict)
	if 'body_html' in result:
		result['html'] = result.pop('body_html')
	# Create sender object from joined data
	sender_email = result.pop('sender_email', None)
	if sender_email:
		result['sender'] = {'email': sender_email, 'name': None}
	# Create recipient object from joined data
	recipient_email = result.pop('recipient_email', None)
	if recipient_email:
		result['recipient'] = {'email': recipient_email, 'name': None}
	return result


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
	          sender_email:
	            type: string
	          recipient_email:
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
	cursor.execute('''
		SELECT e.*, 
		       s.email as sender_email, 
		       r.email as recipient_email
		FROM emails e
		LEFT JOIN users s ON e.sender_id = s.id
		LEFT JOIN users r ON e.recipient_id = r.id
		WHERE e.recipient_id = %s OR e.sender_id = %s
		ORDER BY e.created_at DESC
	''', (request.current_user['id'], request.current_user['id']))
	emails = cursor.fetchall()
	cursor.close()
	conn.close()
	return jsonify([format_email_response(dict(e)) for e in emails])

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
	cursor.execute('''
		SELECT e.*, 
		       s.email as sender_email, 
		       r.email as recipient_email
		FROM emails e
		LEFT JOIN users s ON e.sender_id = s.id
		LEFT JOIN users r ON e.recipient_id = r.id
		WHERE e.id = %s AND (e.recipient_id = %s OR e.sender_id = %s)
	''', (email_id, request.current_user['id'], request.current_user['id']))
	email = cursor.fetchone()
	cursor.close()
	conn.close()
	if not email:
		return jsonify({'error': 'Email not found'}), 404
	return jsonify(format_email_response(dict(email)))

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
			cursor.execute('SELECT id FROM users WHERE email = %s AND is_local = TRUE', (recipient_email,))
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
	
	# For local recipients (or mixed), create email in Sent folder
	# Get or create Sent folder
	cursor.execute(
		'SELECT id FROM folders WHERE user_id = %s AND name = %s',
		(request.current_user['id'], 'Sent')
	)
	folder = cursor.fetchone()
	if folder:
		folder_id = folder['id']
	else:
		cursor.execute(
			'INSERT INTO folders (user_id, name) VALUES (%s, %s) RETURNING id',
			(request.current_user['id'], 'Sent')
		)
		folder_id = cursor.fetchone()['id']
	
	# Determine recipient_id: first local recipient or None
	recipient_id = local_recipients[0][1] if local_recipients else None
	
	cursor.execute(
		'INSERT INTO emails (sender_id, recipient_id, subject, body, folder_id) VALUES (%s, %s, %s, %s, %s) RETURNING id',
		(request.current_user['id'], recipient_id, data.get('subject'), data.get('body'), folder_id)
	)
	email_id = cursor.fetchone()['id']
	
	# Add local recipients and create copies in their inboxes
	for recipient_email, recipient_id in local_recipients:
		cursor.execute(
			'INSERT INTO email_recipients (email_id, user_id, recipient_type) VALUES (%s, %s, %s)',
			(email_id, recipient_id, 'to')
		)
		
		# Get or create recipient's Inbox folder
		cursor.execute(
			'SELECT id FROM folders WHERE user_id = %s AND name = %s',
			(recipient_id, 'Inbox')
		)
		inbox = cursor.fetchone()
		if not inbox:
			cursor.execute(
				'INSERT INTO folders (user_id, name) VALUES (%s, %s) RETURNING id',
				(recipient_id, 'Inbox')
			)
			inbox = cursor.fetchone()
		
		# Create copy in recipient's Inbox
		cursor.execute(
			'INSERT INTO emails (sender_id, recipient_id, subject, body, folder_id) VALUES (%s, %s, %s, %s, %s)',
			(request.current_user['id'], recipient_id, data.get('subject'), data.get('body'), inbox['id'])
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

@bp.route('/api/emails/mime', methods=['POST'])
@token_required
def create_mime_email():
	"""
	Create a new email from raw MIME content with embedded images
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
	        - mime_content
	      properties:
	        to:
	          type: string
	          description: Recipient email address
	        mime_content:
	          type: string
	          description: Raw MIME multipart message content
	responses:
	  201:
	    description: Email created successfully
	    schema:
	      type: object
	      properties:
	        id:
	          type: integer
	        queued:
	          type: boolean
	        status:
	          type: string
	  400:
	    description: Invalid MIME content
	  401:
	    description: Unauthorized
	"""
	data = request.get_json()
	
	if not data or 'mime_content' not in data:
		return jsonify({'error': 'mime_content is required'}), 400
	
	mime_content = data.get('mime_content')
	to_address = data.get('to')
	
	if not to_address:
		return jsonify({'error': 'to is required'}), 400
	
	try:
		# Parse the MIME message
		msg = message_from_string(mime_content)
		
		# Validate it's a valid MIME message
		if not msg:
			return jsonify({'error': 'Failed to parse MIME message'}), 400
		
		# Get sender's email from current user
		conn = get_db_connection()
		cursor = conn.cursor()
		cursor.execute('SELECT email FROM users WHERE id = %s', (request.current_user['id'],))
		sender_row = cursor.fetchone()
		cursor.close()
		conn.close()
		
		if not sender_row:
			return jsonify({'error': 'Sender not found'}), 400
		
		from_address = sender_row['email']
		
		# Ensure the MIME message has proper From header
		if not msg.get('From'):
			msg['From'] = from_address
		
		# Ensure the MIME message has proper To header
		if not msg.get('To'):
			msg['To'] = to_address
		
		# Ensure the MIME message has a Message-ID
		if not msg.get('Message-ID'):
			import uuid
			msg['Message-ID'] = f"<{uuid.uuid4()}@{from_address.split('@')[-1]}>"
		
		# The parsed message is a Message object
		# Ensure required headers are present
		if not msg.get('Subject'):
			msg['Subject'] = 'No Subject'
		
		# Import and use the queue function
		from smtp_server.outbound.storage import queue_outbound_email
		
		# Determine recipients
		to_addresses = [to_address] if isinstance(to_address, str) else to_address
		
		# Extract subject and body for database storage
		subject = msg.get('Subject', '')
		
		# For MIME emails, store the full MIME content in body
		# (not just a preview) so embedded images are preserved
		body_preview = mime_content
		
		# Prepare headers - clean any newlines that could break DKIM
		headers_dict = {}
		for key, value in msg.items():
			# Remove any newlines from header values to prevent DKIM issues
			clean_value = str(value).replace('\n', ' ').replace('\r', ' ')
			headers_dict[key] = clean_value
		
		# Queue the email
		email_id, queue_ids = queue_outbound_email(
			sender_id=request.current_user['id'],
			from_address=from_address,
			to_addresses=to_addresses,
			subject=subject,
			body=body_preview,
			message=msg,
			headers=headers_dict
		)
		
		logger.info(f"MIME email queued: ID={email_id}, recipients={to_addresses}")
		
		# Extract and save attachments from MIME content
		from email.policy import default
		import io
		
		parsed_msg = message_from_string(mime_content, policy=default)
		
		for part in parsed_msg.walk():
			content_disposition = part.get('Content-Disposition', '')
			content_type = part.get_content_type()
			
			# Skip multipart containers
			if part.get_content_maintype() == 'multipart':
				continue
			
			# Only include parts with attachment content-disposition and a filename
			filename = part.get_filename()
			if not filename:
				continue
			
			# Skip inline parts that are the body (text, html)
			if 'inline' in content_disposition:
				continue
			
			# Get content type and size
			content_type = part.get_content_type()
			
			# Get decoded payload
			try:
				payload = part.get_payload(decode=True)
				if payload:
					file_size = len(payload)
				else:
					continue
			except:
				continue
			
			# Save attachment record (without file content - stored in MIME)
			conn = get_db_connection()
			cursor = conn.cursor()
			cursor.execute(
				'''INSERT INTO attachments (email_id, file_name, content_type, file_size, created_at)
				   VALUES (%s, %s, %s, %s, NOW()) RETURNING id''',
				(email_id, filename, content_type, file_size)
			)
			conn.commit()
			cursor.close()
			conn.close()
			logger.info(f"Saved attachment: {filename} for email {email_id}")
		
		return jsonify({
			'id': email_id,
			'queued': len(queue_ids) > 0,
			'status': 'pending'
		}), 201
		
	except Exception as e:
		logger.error(f"Error processing MIME email: {e}")
		return jsonify({'error': f'Invalid MIME content: {str(e)}'}), 400

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
	cursor.execute('DELETE FROM emails WHERE id = %s AND recipient_id = %s', (email_id, request.current_user['id']))
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

@bp.route('/api/emails/<int:email_id>/delivery-status', methods=['GET'])
@token_required
def get_delivery_status(email_id):
	"""
	Get delivery status for an outbound email
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
	    description: Delivery status retrieved
	    schema:
	      type: object
	      properties:
	        email_id:
	          type: integer
	        status:
	          type: string
	          description: Overall status (pending, sending, sent, failed, retry, not_found)
	        queue_entries:
	          type: array
	          items:
	            type: object
	            properties:
	              recipient:
	                type: string
	              status:
	                type: string
	              attempts:
	                type: integer
	              last_attempt:
	                type: string
	                format: date-time
	              delivered_at:
	                type: string
	                format: date-time
	              error:
	                type: string
	        logs:
	          type: array
	          items:
	            type: object
	            properties:
	              event:
	                type: string
	              smtp_response:
	                type: string
	              error:
	                type: string
	              remote_server:
	                type: string
	              timestamp:
	                type: string
	                format: date-time
	  404:
	    description: Email not found or not an outbound email
	  401:
	    description: Unauthorized
	"""
	conn = get_db_connection()
	cursor = conn.cursor()
	
	# Verify email exists and belongs to user
	cursor.execute(
		'SELECT id FROM emails WHERE id = %s AND sender_id = %s',
		(email_id, request.current_user['id'])
	)
	email = cursor.fetchone()
	if not email:
		cursor.close()
		conn.close()
		return jsonify({'error': 'Email not found'}), 404
	
	# Get queue entries for this email
	cursor.execute(
		'''SELECT id, recipient_email, status, attempt_count, 
		   last_attempt, delivered_at, error_message
		   FROM outbound_queue
		   WHERE email_id = %s''',
		(email_id,)
	)
	queue_entries = cursor.fetchall()
	
	if not queue_entries:
		cursor.close()
		conn.close()
		return jsonify({
			'email_id': email_id,
			'status': 'not_found',
			'message': 'No outbound delivery record found for this email'
		}), 200
	
	# Determine overall status
	statuses = [entry['status'] for entry in queue_entries]
	if 'sent' in statuses and all(s == 'sent' for s in statuses):
		overall_status = 'sent'
	elif 'failed' in statuses:
		overall_status = 'failed'
	elif 'sending' in statuses:
		overall_status = 'sending'
	elif 'retry' in statuses:
		overall_status = 'retry'
	else:
		overall_status = 'pending'
	
	# Get delivery logs
	cursor.execute(
		'''SELECT event_type, smtp_response, error_message, 
		   remote_server, created_at
		   FROM delivery_logs
		   WHERE email_id = %s
		   ORDER BY created_at DESC''',
		(email_id,)
	)
	logs = cursor.fetchall()
	
	cursor.close()
	conn.close()
	
	return jsonify({
		'email_id': email_id,
		'status': overall_status,
		'queue_entries': [
			{
				'recipient': entry['recipient_email'],
				'status': entry['status'],
				'attempts': entry['attempt_count'],
				'last_attempt': entry['last_attempt'].isoformat() if entry['last_attempt'] else None,
				'delivered_at': entry['delivered_at'].isoformat() if entry['delivered_at'] else None,
				'error': entry['error_message']
			}
			for entry in queue_entries
		],
		'logs': [
			{
				'event': log['event_type'],
				'smtp_response': log['smtp_response'],
				'error': log['error_message'],
				'remote_server': log['remote_server'],
				'timestamp': log['created_at'].isoformat()
			}
			for log in logs
		]
	}), 200
