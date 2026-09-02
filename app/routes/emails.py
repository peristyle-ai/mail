from flask import Blueprint, request, jsonify
from app.utils.auth import token_required
from ..db import get_db_connection
import logging
import uuid as _uuid
from email import message_from_string
from email.message import EmailMessage
from email.policy import default
from email.utils import getaddresses

bp = Blueprint('emails', __name__)
logger = logging.getLogger(__name__)


def decode_rfc2047(s):
	"""Decode RFC 2047 encoded subject strings."""
	if not s or '=?' not in s:
		return s
	from email.header import decode_header
	try:
		parts = decode_header(s)
		decoded = ''
		for part, charset in parts:
			if isinstance(part, bytes):
				decoded += part.decode(charset or 'utf-8', errors='replace')
			else:
				decoded += part
		return decoded
	except Exception:
		return s


def looks_like_raw_email(content):
	"""Detect stored RFC 822/MIME content in the body column."""
	if not content:
		return False
	stripped = content.lstrip()
	if '\n\n' not in content and '\r\n\r\n' not in content:
		return False
	return stripped.startswith((
		'Content-Type:', 'MIME-Version:', 'Subject:', 'From:',
		'To:', 'Date:', 'Message-ID:', 'Return-Path:', 'Delivered-To:'
	))

def format_email_response(email_dict):
	"""Format email dict for API response, mapping body_html to html and adding email addresses."""
	result = dict(email_dict)
	if 'body_html' in result:
		result['html'] = result.pop('body_html')
	if 'subject' in result:
		result['subject'] = decode_rfc2047(result['subject'])
	# Fix body/html that may contain raw MIME instead of extracted content
	body = result.get('body') or ''
	html = result.get('html') or result.get('body_html') or ''
	if looks_like_raw_email(body):
		try:
			parsed = message_from_string(body)
			from smtp_server.email_storage import extract_bodies
			extracted_text, extracted_html = extract_bodies(parsed)
			if extracted_text:
				result['body'] = extracted_text
			if extracted_html:
				result['html'] = extracted_html
			elif not html and extracted_text:
				result['html'] = ''
		except Exception:
			pass
	# Create sender object from joined data
	sender_email = result.pop('sender_email', None)
	if sender_email:
		result['sender'] = {'email': sender_email, 'name': None}
	# Create recipient object from joined data
	recipient_email = result.pop('recipient_email', None)
	if recipient_email:
		result['recipient'] = {'email': recipient_email, 'name': None}
	# Include folder name in response
	folder_name = result.pop('folder_name', None)
	if folder_name:
		result['folder'] = folder_name
	# --- Threading fields (RFC 2822) - additive, only present when set ---
	# Normalize None to omitted so the JSON is clean for older clients.
	for threading_field in ('message_id', 'in_reply_to', 'references_chain', 'thread_id'):
		val = result.get(threading_field)
		if val is None:
			result.pop(threading_field, None)
		elif threading_field == 'thread_id':
			# Always serialize as a plain UUID string for the API.
			result[threading_field] = str(val)
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
	folder_name = request.args.get('folder')
	thread_id = (request.args.get('thread') or '').strip() or None
	if thread_id:
		try:
			_uuid.UUID(thread_id)
		except ValueError:
			return jsonify({'error': 'invalid thread id'}), 400
	conn = get_db_connection()
	cursor = conn.cursor()
	if folder_name and thread_id:
		cursor.execute('''
			SELECT e.*,
			       s.email as sender_email,
			       r.email as recipient_email,
			       f.name as folder_name
			FROM emails e
			LEFT JOIN users s ON e.sender_id = s.id
			LEFT JOIN users r ON e.recipient_id = r.id
			JOIN folders f ON e.folder_id = f.id
			WHERE f.user_id = %s AND f.name = %s AND e.thread_id = %s
			ORDER BY e.created_at DESC
		''', (request.current_user['id'], folder_name, thread_id))
	elif folder_name:
		cursor.execute('''
			SELECT e.*,
			       s.email as sender_email,
			       r.email as recipient_email,
			       f.name as folder_name
			FROM emails e
			LEFT JOIN users s ON e.sender_id = s.id
			LEFT JOIN users r ON e.recipient_id = r.id
			JOIN folders f ON e.folder_id = f.id
			WHERE f.user_id = %s AND f.name = %s
			ORDER BY e.created_at DESC
		''', (request.current_user['id'], folder_name))
	elif thread_id:
		cursor.execute('''
			SELECT e.*,
			       s.email as sender_email,
			       r.email as recipient_email,
			       f.name as folder_name
			FROM emails e
			LEFT JOIN users s ON e.sender_id = s.id
			LEFT JOIN users r ON e.recipient_id = r.id
			JOIN folders f ON e.folder_id = f.id
			WHERE f.user_id = %s AND e.thread_id = %s
			ORDER BY e.created_at DESC
		''', (request.current_user['id'], thread_id))
	else:
		cursor.execute('''
			SELECT e.*,
			       s.email as sender_email,
			       r.email as recipient_email,
			       f.name as folder_name
			FROM emails e
			LEFT JOIN users s ON e.sender_id = s.id
			LEFT JOIN users r ON e.recipient_id = r.id
			JOIN folders f ON e.folder_id = f.id
			WHERE f.user_id = %s
			ORDER BY e.created_at DESC
		''', (request.current_user['id'],))
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
		       r.email as recipient_email,
		       f.name as folder_name
		FROM emails e
		LEFT JOIN users s ON e.sender_id = s.id
		LEFT JOIN users r ON e.recipient_id = r.id
		JOIN folders f ON e.folder_id = f.id
		WHERE e.id = %s AND f.user_id = %s
	''', (email_id, request.current_user['id']))
	email = cursor.fetchone()
	cursor.close()
	conn.close()
	if not email:
		return jsonify({'error': 'Email not found'}), 404
	return jsonify(format_email_response(dict(email)))

def _normalize_recipient_list(value, field_name, cursor, conn):
	"""Normalize a string-or-list recipient field into a clean list of strings.

	Returns a tuple of (normalized_list, error_response_tuple_or_None).
	"""
	if value is None:
		return [], None
	if isinstance(value, str):
		value = [value]
	if not isinstance(value, list):
		return None, (jsonify({'error': f'{field_name} must be a string or array of strings'}), 400)

	normalized = []
	for entry in value:
		if not isinstance(entry, str):
			return None, (jsonify({'error': f'each entry in {field_name} must be a string'}), 400)
		entry = entry.strip()
		if not entry:
			return None, (jsonify({'error': f'{field_name} entries cannot be empty'}), 400)
		normalized.append(entry)
	return normalized, None


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
	          oneOf:
	            - type: string
	            - type: array
	              items:
	                type: string
	          description: |
	            Recipient email address(es). String for one recipient, or array of
	            strings for multiple.
	        cc:
	          oneOf:
	            - type: string
	            - type: array
	              items:
	                type: string
	          description: |
	            Optional CC recipient email address(es). Same shape as `to`.
	            Both local users and external addresses are supported.
	        subject:
	          type: string
	          description: Email subject
	        body:
	          type: string
	          description: Email body
	        folder_id:
	          type: integer
	          description: Folder ID to store email in
	        in_reply_to:
	          type: string
	          description: |
	            Message-ID of the email being replied to (no angle brackets).
	            Used for threading.
	        references:
	          type: string
	          description: |
	            Space-separated Message-ID chain from the email being replied
	            to (no angle brackets). Used for threading.
	responses:
	  201:
	    description: Email created successfully
	    schema:
	      type: object
	      properties:
	        id:
	          type: integer
	        message_id:
	          type: string
	          description: |
	            Generated Message-ID for this email (no angle brackets). Pass
	            it back as `in_reply_to` when replying.
	        thread_id:
	          type: string
	          format: uuid
	          description: UUID of the conversation thread.
	        queued:
	          type: boolean
	        cc_count:
	          type: integer
	          description: Number of CC recipients
	  400:
	    description: Invalid input
	  401:
	    description: Unauthorized
	"""
	data = request.get_json()
	if not data or 'to' not in data:
		return jsonify({'error': 'to is required'}), 400

	conn = get_db_connection()
	cursor = conn.cursor()

	cursor.execute('SELECT email FROM users WHERE id = %s', (request.current_user['id'],))
	sender_row = cursor.fetchone()
	if not sender_row:
		cursor.close()
		conn.close()
		return jsonify({'error': 'Sender not found'}), 400
	from_address = sender_row['email']

	normalized_recipients, err = _normalize_recipient_list(data.get('to'), 'to', cursor, conn)
	if err:
		cursor.close()
		conn.close()
		return err
	if not normalized_recipients:
		cursor.close()
		conn.close()
		return jsonify({'error': 'at least one recipient is required'}), 400

	normalized_cc, err = _normalize_recipient_list(data.get('cc'), 'cc', cursor, conn)
	if err:
		cursor.close()
		conn.close()
		return err

	cursor.close()
	conn.close()

	from email.message import EmailMessage as EM
	from smtp_server.outbound.storage import queue_outbound_email

	msg = EM()
	msg['Subject'] = data.get('subject', '')
	msg['From'] = from_address
	msg['To'] = ', '.join(normalized_recipients)
	if normalized_cc:
		msg['Cc'] = ', '.join(normalized_cc)
	msg.set_content(data.get('body', ''))

	# --- Threading fields (optional; for replies) ---
	in_reply_to = (data.get('in_reply_to') or '').strip() or None
	references = (data.get('references') or '').strip() or None
	# Validate formats: must be bare Message-IDs (no angle brackets).
	for label, val in (('in_reply_to', in_reply_to), ('references', references)):
		if val and ('<' in val or '>' in val):
			return jsonify({'error': f'{label} must not contain angle brackets'}), 400

	try:
		email_id, queue_ids = queue_outbound_email(
			sender_id=request.current_user['id'],
			from_address=from_address,
			to_addresses=normalized_recipients,
			cc_addresses=normalized_cc,
			subject=data.get('subject', ''),
			body=data.get('body', ''),
			message=msg,
			headers=dict(msg.items()),
			in_reply_to=in_reply_to,
			references=references,
		)
		# Pull the generated Message-ID + thread_id back from the stored Sent row.
		# queue_outbound_email set them on `msg` (which is what was stored in
		# raw_email), so they're consistent.
		stored_message_id = msg.get('Message-ID', '').strip().lstrip('<').rstrip('>') or None
		conn = get_db_connection()
		c = conn.cursor()
		c.execute('SELECT thread_id FROM emails WHERE id = %s', (email_id,))
		row = c.fetchone()
		c.close()
		conn.close()
		stored_thread_id = str(row['thread_id']) if row and row['thread_id'] else None
		return jsonify({
			'id': email_id,
			'message_id': stored_message_id,
			'thread_id': stored_thread_id,
			'queued': len(queue_ids) > 0,
			'cc_count': len(normalized_cc)
		}), 201
	except Exception as e:
		logger.error(f"Error queueing outbound email: {e}")
		return jsonify({'error': str(e)}), 500

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
	          oneOf:
	            - type: string
	            - type: array
	              items:
	                type: string
	          description: Recipient email address(es)
	        cc:
	          oneOf:
	            - type: string
	            - type: array
	              items:
	                type: string
	          description: |
	            Optional CC recipient(s). If omitted, the Cc: header from the
	            parsed MIME message is used (when present). The request-level
	            `cc` field takes priority over a Cc: header in the MIME.
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
	        cc_count:
	          type: integer
	          description: Number of CC recipients
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
		if not sender_row:
			cursor.close()
			conn.close()
			return jsonify({'error': 'Sender not found'}), 400
		from_address = sender_row['email']

		# Normalize request-level to / cc (string or array).
		normalized_recipients, err = _normalize_recipient_list(data.get('to'), 'to', cursor, conn)
		if err:
			cursor.close()
			conn.close()
			return err
		if not normalized_recipients:
			cursor.close()
			conn.close()
			return jsonify({'error': 'at least one recipient is required'}), 400

		normalized_cc, err = _normalize_recipient_list(data.get('cc'), 'cc', cursor, conn)
		if err:
			cursor.close()
			conn.close()
			return err

		cursor.close()
		conn.close()

		# Fall back to extracting Cc from the parsed MIME message if the
		# request didn't supply `cc`. The request-level value wins when present.
		if not normalized_cc and msg.get('Cc'):
			parsed_cc = [addr for name, addr in getaddresses([str(msg.get('Cc'))]) if addr]
			if parsed_cc:
				normalized_cc = parsed_cc
				# Replace the existing Cc header (del + add) to avoid duplicate
				# Cc headers when the parsed message already had one.
				del msg['Cc']
				msg['Cc'] = ', '.join(parsed_cc)

		# Ensure the MIME message has proper From header
		if not msg.get('From'):
			msg['From'] = from_address

		# Ensure the MIME message has proper To header (preserve any
		# Cc that the caller already supplied)
		if not msg.get('To') or all(addr not in str(msg.get('To', '')) for addr in normalized_recipients):
			msg['To'] = ', '.join(normalized_recipients)

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

		to_addresses = normalized_recipients

		from smtp_server.email_storage import extract_subject, extract_bodies

		subject = extract_subject(msg)
		plain_text, body_html_from_msg = extract_bodies(msg)
		body_preview = plain_text

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
			cc_addresses=normalized_cc,
			subject=subject,
			body=body_preview,
			message=msg,
			headers=headers_dict
		)

		logger.info(f"MIME email queued: ID={email_id}, recipients={to_addresses} (cc={len(normalized_cc)})")
		
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
		
		# Pull the generated Message-ID + thread_id back from the stored Sent row.
		stored_message_id = msg.get('Message-ID', '').strip().lstrip('<').rstrip('>') or None
		conn = get_db_connection()
		c = conn.cursor()
		c.execute('SELECT thread_id FROM emails WHERE id = %s', (email_id,))
		row = c.fetchone()
		c.close()
		conn.close()
		stored_thread_id = str(row['thread_id']) if row and row['thread_id'] else None

		return jsonify({
			'id': email_id,
			'message_id': stored_message_id,
			'thread_id': stored_thread_id,
			'queued': len(queue_ids) > 0,
			'cc_count': len(normalized_cc),
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
	cursor.execute('UPDATE emails SET is_read = TRUE FROM folders f WHERE emails.folder_id = f.id AND emails.id = %s AND f.user_id = %s', (email_id, request.current_user['id']))
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
	cursor.execute('SELECT e.is_starred FROM emails e JOIN folders f ON e.folder_id = f.id WHERE e.id = %s AND f.user_id = %s', (email_id, request.current_user['id']))
	email = cursor.fetchone()
	if not email:
		return jsonify({'error': 'Email not found'}), 404
	new_state = not email['is_starred']
	cursor.execute('UPDATE emails SET is_starred = %s FROM folders f WHERE emails.folder_id = f.id AND emails.id = %s AND f.user_id = %s', (new_state, email_id, request.current_user['id']))
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
	cursor.execute('DELETE FROM emails USING folders f WHERE emails.folder_id = f.id AND emails.id = %s AND f.user_id = %s', (email_id, request.current_user['id']))
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
	cursor.execute('UPDATE emails SET folder_id = %s FROM folders f WHERE emails.folder_id = f.id AND emails.id = %s AND f.user_id = %s', (data['folder_id'], email_id, request.current_user['id']))
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
	
	# Verify email exists and belongs to user (delivery status is for sent emails)
	cursor.execute(
		'SELECT e.id FROM emails e JOIN folders f ON e.folder_id = f.id WHERE e.id = %s AND f.user_id = %s',
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


# =============================================================================
# Thread endpoints (PR4)
# =============================================================================
#
# A thread is "visible" to user U if at least one email in the thread:
#   - lives in a folder owned by U
#   - AND lists U as sender or recipient
#
# This matches the per-email authorization rule used elsewhere
# (see coding_agent/plan_threading.md D3). All four endpoints below
# apply this gate consistently via _user_can_see_thread().

def _user_can_see_thread(cursor, user_id: int, thread_id: str) -> bool:
	"""Return True if `user_id` is a sender or recipient of at least one
	email in `thread_id` whose folder they own."""
	cursor.execute(
		"""
		SELECT EXISTS (
			SELECT 1 FROM emails e
			JOIN folders f ON e.folder_id = f.id
			LEFT JOIN email_recipients er ON er.email_id = e.id
			WHERE e.thread_id = %s
			  AND f.user_id = %s
			  AND (e.sender_id = %s OR er.user_id = %s)
		) AS visible
		""",
		(thread_id, user_id, user_id, user_id),
	)
	row = cursor.fetchone()
	return bool(row and row['visible'])


@bp.route('/api/threads', methods=['GET'])
@token_required
def list_threads():
	"""
	List collapsed thread summaries for the current user.

	Query params:
	  folder: filter to threads touching this folder (Inbox, Sent, ...)
	  limit:  page size (default 50)
	  offset: pagination offset
	  q:      substring search on subject
	---
	tags:
	  - Threads
	security:
	  - Bearer: []
	responses:
	  200:
		description: Threads list
	"""
	folder_filter = (request.args.get('folder') or '').strip()
	limit = min(int(request.args.get('limit', 50) or 50), 200)
	offset = max(int(request.args.get('offset', 0) or 0), 0)
	q = (request.args.get('q') or '').strip()
	user_id = request.current_user['id']

	conn = get_db_connection()
	cursor = conn.cursor()
	try:
		# Build the WHERE clause incrementally. The visible-rows CTE is
		# shared with /api/threads/<id>/messages etc. - keep its shape
		# stable.
		where = [
			"f.user_id = %s",
			"(e.sender_id = %s OR er.user_id = %s)",
			"e.thread_id IS NOT NULL",
		]
		params = [ user_id, user_id, user_id ]
		if folder_filter:
			where.append("f.name = %s")
			params.append(folder_filter)
		if q:
			where.append("e.subject ILIKE %s")
			params.append(f"%{q}%")
		where_sql = " AND ".join(where)

		# Aggregate counts
		cursor.execute(
			f"""
			WITH visible AS (
				SELECT e.*
				FROM emails e
				JOIN folders f ON e.folder_id = f.id
				LEFT JOIN email_recipients er ON er.email_id = e.id
				WHERE {where_sql}
			),
			ranked AS (
				SELECT thread_id,
				       MAX(created_at) AS last_message_at,
				       COUNT(*) AS message_count,
				       SUM(CASE WHEN is_read THEN 0 ELSE 1 END) AS unread_count
				FROM visible
				GROUP BY thread_id
			),
			latest AS (
				SELECT DISTINCT ON (v.thread_id)
				       v.thread_id,
				       v.subject,
				       v.subject_normalized,
				       v.body,
				       v.created_at,
				       v.is_read,
				       s.email AS sender_email,
				       s.name AS sender_name
				FROM visible v
				JOIN users s ON v.sender_id = s.id
				ORDER BY v.thread_id, v.created_at DESC
			)
			SELECT r.thread_id,
			       l.subject,
			       l.subject_normalized,
			       LEFT(COALESCE(l.body, ''), 240) AS preview,
			       r.message_count,
			       r.unread_count,
			       l.sender_email,
			       l.sender_name,
			       r.last_message_at
			FROM ranked r JOIN latest l USING (thread_id)
			ORDER BY r.last_message_at DESC
			LIMIT %s OFFSET %s
			""",
			params + [ limit, offset ],
		)
		rows = cursor.fetchall()
		threads = []
		for r in rows:
			threads.append({
				'thread_id': str(r['thread_id']),
				'subject': r['subject'],
				'subject_normalized': r['subject_normalized'],
				'preview': r['preview'],
				'message_count': r['message_count'],
				'unread_count': r['unread_count'],
				'last_message_at': (
					r['last_message_at'].isoformat() if r['last_message_at'] else None
				),
				'last_sender': {
					'email': r['sender_email'],
					'name': r['sender_name'],
				},
				# Per-thread participants (sender + recipient set across all
				# emails in the thread).
			})

		# Bulk-load participants + folders per thread
		if threads:
			thread_ids = [t['thread_id'] for t in threads]
			cursor.execute(
				"""
				SELECT e.thread_id,
				       ARRAY_AGG(DISTINCT s.email) FILTER (WHERE s.email IS NOT NULL) AS senders,
				       ARRAY_AGG(DISTINCT r.email) FILTER (WHERE r.email IS NOT NULL) AS recipients,
				       ARRAY_AGG(DISTINCT f.name) FILTER (WHERE f.name IS NOT NULL) AS folders
				FROM emails e
				JOIN folders f ON e.folder_id = f.id
				LEFT JOIN users s ON e.sender_id = s.id
				LEFT JOIN email_recipients er ON er.email_id = e.id
				LEFT JOIN users r ON er.user_id = r.id
				WHERE e.thread_id = ANY(%s::uuid[]) AND f.user_id = %s
				GROUP BY e.thread_id
				""",
				(thread_ids, user_id),
			)
			agg_rows = cursor.fetchall()
			agg = {str(r['thread_id']): r for r in agg_rows}
			for t in threads:
				a = agg.get(t['thread_id'])
				if not a:
					continue
				participants = sorted(
					{(a['senders'] or []), (a['recipients'] or [])}
					if False else set((a['senders'] or []) + (a['recipients'] or []))
				)
				t['participants'] = [
					{'email': e, 'name': None} for e in participants
				]
				t['folders'] = sorted(set(a['folders'] or []))
			# Default empty participants/folders if no aggregation row
			for t in threads:
				t.setdefault('participants', [])
				t.setdefault('folders', [])

		# Total count for pagination
		cursor.execute(
			f"""
			SELECT COUNT(DISTINCT e.thread_id) AS total
			FROM emails e
			JOIN folders f ON e.folder_id = f.id
			LEFT JOIN email_recipients er ON er.email_id = e.id
			WHERE {where_sql} AND e.thread_id IS NOT NULL
			""",
			params,
		)
		total = cursor.fetchone()['total']

		return jsonify({
			'threads': threads,
			'total': total,
			'limit': limit,
			'offset': offset,
		}), 200
	finally:
		cursor.close()
		conn.close()


@bp.route('/api/threads/<thread_id>/messages', methods=['GET'])
@token_required
def list_thread_messages(thread_id):
	"""
	Return every message in the thread, chronological order.
	---
	tags:
	  - Threads
	security:
	  - Bearer: []
	parameters:
	  - in: path
	    name: thread_id
	    type: string
	    required: true
	responses:
	  200:
		description: Thread messages
	  404:
		description: Thread not visible to user
	"""
	try:
		_uuid.UUID(thread_id)
	except (ValueError, AttributeError):
		return jsonify({'error': 'invalid thread_id'}), 400

	user_id = request.current_user['id']
	conn = get_db_connection()
	cursor = conn.cursor()
	try:
		if not _user_can_see_thread(cursor, user_id, thread_id):
			return jsonify({'error': 'thread not found'}), 404

		cursor.execute(
			"""
			SELECT e.id, e.message_id, e.in_reply_to, e.subject, e.body,
			       e.body_html, e.is_read, e.is_starred, e.created_at,
			       s.email AS sender_email, s.name AS sender_name,
			       r.email AS recipient_email, r.name AS recipient_name,
			       f.name AS folder_name
			FROM emails e
			JOIN folders f ON e.folder_id = f.id
			JOIN users s ON e.sender_id = s.id
			LEFT JOIN email_recipients er ON er.email_id = e.id
			LEFT JOIN users r ON er.user_id = r.id
			WHERE e.thread_id = %s
			  AND f.user_id = %s
			ORDER BY e.created_at ASC, e.id ASC
		""",
			(thread_id, user_id),
		)
		rows = cursor.fetchall()
		messages = []
		for r in rows:
			messages.append({
				'id': r['id'],
				'message_id': r['message_id'],
				'in_reply_to': r['in_reply_to'],
				'sender': {
					'email': r['sender_email'],
					'name': r['sender_name'],
				},
				'recipient': {
					'email': r['recipient_email'],
					'name': r['recipient_name'],
				} if r['recipient_email'] else None,
				'folder': r['folder_name'],
				'subject': r['subject'],
				'body': r['body'],
				'html': r['body_html'],
				'is_read': r['is_read'],
				'is_starred': r['is_starred'],
				'created_at': (
					r['created_at'].isoformat() if r['created_at'] else None
				),
			})

        # First row's subject as the thread's subject
		subject = rows[0]['subject'] if rows else None
		subject_normalized = rows[0].get('subject_normalized') if rows else None

		return jsonify({
			'thread_id': thread_id,
			'subject': subject,
			'messages': messages,
		}), 200
	finally:
		cursor.close()
		conn.close()


@bp.route('/api/threads/<thread_id>/read', methods=['POST'])
@token_required
def mark_thread_read(thread_id):
	"""
	Mark every message in the thread as read for the current user.
	---
	tags:
	  - Threads
	security:
	  - Bearer: []
	parameters:
	  - in: path
	    name: thread_id
	    type: string
	    required: true
	responses:
	  200:
		description: Marked read
	  404:
		description: Thread not visible to user
	"""
	try:
		_uuid.UUID(thread_id)
	except (ValueError, AttributeError):
		return jsonify({'error': 'invalid thread_id'}), 400

	user_id = request.current_user['id']
	conn = get_db_connection()
	cursor = conn.cursor()
	try:
		if not _user_can_see_thread(cursor, user_id, thread_id):
			return jsonify({'error': 'thread not found'}), 404

		cursor.execute(
			"""
			UPDATE emails
			SET is_read = TRUE
			WHERE id IN (
				SELECT e.id FROM emails e
				JOIN folders f ON e.folder_id = f.id
				LEFT JOIN email_recipients er ON er.email_id = e.id
				WHERE e.thread_id = %s
				  AND f.user_id = %s
				  AND (e.sender_id = %s OR er.user_id = %s)
			)
		""",
			(thread_id, user_id, user_id, user_id),
		)
		conn.commit()
		return jsonify({'status': 'read', 'affected': cursor.rowcount}), 200
	finally:
		cursor.close()
		conn.close()


@bp.route('/api/threads/<thread_id>/star', methods=['PATCH'])
@token_required
def toggle_thread_star(thread_id):
	"""
	Star / un-star every message in the thread for the current user.
	Toggles to the OPPOSITE of the current state of the first message.
	---
	tags:
	  - Threads
	security:
	  - Bearer: []
	parameters:
	  - in: path
	    name: thread_id
	    type: string
	    required: true
	responses:
	  200:
		description: Toggled
	  404:
		description: Thread not visible to user
	"""
	try:
		_uuid.UUID(thread_id)
	except (ValueError, AttributeError):
		return jsonify({'error': 'invalid thread_id'}), 400

	user_id = request.current_user['id']
	conn = get_db_connection()
	cursor = conn.cursor()
	try:
		if not _user_can_see_thread(cursor, user_id, thread_id):
			return jsonify({'error': 'thread not found'}), 404

		# Determine new state from any one message in the thread.
		cursor.execute(
			"""
			SELECT is_starred FROM emails e
			JOIN folders f ON e.folder_id = f.id
			LEFT JOIN email_recipients er ON er.email_id = e.id
			WHERE e.thread_id = %s
			  AND f.user_id = %s
			  AND (e.sender_id = %s OR er.user_id = %s)
			ORDER BY e.id ASC
			LIMIT 1
		""",
			(thread_id, user_id, user_id, user_id),
		)
		row = cursor.fetchone()
		if not row:
			return jsonify({'error': 'thread not found'}), 404
		new_state = not bool(row['is_starred'])

		cursor.execute(
			"""
			UPDATE emails
			SET is_starred = %s
			WHERE id IN (
				SELECT e.id FROM emails e
				JOIN folders f ON e.folder_id = f.id
				LEFT JOIN email_recipients er ON er.email_id = e.id
				WHERE e.thread_id = %s
				  AND f.user_id = %s
				  AND (e.sender_id = %s OR er.user_id = %s)
			)
		""",
			(new_state, thread_id, user_id, user_id, user_id),
		)
		conn.commit()
		return jsonify({'is_starred': new_state, 'affected': cursor.rowcount}), 200
	finally:
		cursor.close()
		conn.close()
