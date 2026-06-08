"""
Outbound Email Storage Module

Handles queuing outgoing emails and tracking delivery status.
"""

import logging
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
from email.message import EmailMessage

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import get_db_connection

logger = logging.getLogger(__name__)


def get_or_create_sent_folder(user_id: int) -> int:
	"""Get or create the Sent folder for a user."""
	conn = get_db_connection()
	cursor = conn.cursor()
	
	try:
		# Check if Sent folder exists
		cursor.execute(
			'SELECT id FROM folders WHERE user_id = %s AND name = %s',
			(user_id, 'Sent')
		)
		result = cursor.fetchone()
		
		if result:
			return result['id']
		
		# Create Sent folder
		cursor.execute(
			'''INSERT INTO folders (user_id, name, created_at)
			   VALUES (%s, %s, %s)
			   RETURNING id''',
			(user_id, 'Sent', datetime.now(timezone.utc))
		)
		conn.commit()
		folder_id = cursor.fetchone()['id']
		logger.info(f"Created Sent folder for user {user_id}")
		return folder_id
		
	finally:
		cursor.close()
		conn.close()


def queue_outbound_email(
	sender_id: int,
	from_address: str,
	to_addresses: List[str],
	subject: str,
	body: str,
	message: EmailMessage,
	headers: Optional[Dict] = None
) -> Tuple[int, List[int]]:
	"""
	Queue an email for outbound delivery.
	
	Args:
		sender_id: User ID of the sender
		from_address: Sender email address
		to_addresses: List of recipient email addresses
		subject: Email subject
		body: Email body
		message: Complete EmailMessage object
		headers: Optional additional headers
		
	Returns:
		Tuple of (email_id, list_of_queue_ids)
	"""
	from smtp_server.email_storage import extract_bodies

	conn = get_db_connection()
	cursor = conn.cursor()
	
	try:
		# Extract HTML body from message
		_, body_html = extract_bodies(message)
		
		# Get Sent folder
		sent_folder_id = get_or_create_sent_folder(sender_id)
		
		# Convert headers to string
		headers_str = ''
		if headers:
			for key, value in headers.items():
				headers_str += f"{key}: {value}\n"
		
		# Add message headers
		for key, value in message.items():
			headers_str += f"{key}: {value}\n"
		
		# Store raw email content
		raw_email_str = ''
		if message:
			try:
				raw_bytes = message.as_bytes()
				raw_email_str = raw_bytes.decode('utf-8', errors='replace')
			except Exception:
				pass
		
		# First pass: identify local vs external recipients
		queue_ids = []
		local_recipients = []
		
		for to_address in to_addresses:
			domain = to_address.split('@')[-1].lower()
			
			# Check if this is a local domain
			cursor.execute('SELECT id FROM users WHERE email = %s AND is_local = TRUE', (to_address,))
			local_user = cursor.fetchone()
			
			if local_user:
				# Local delivery - store in recipient's inbox
				local_recipients.append((to_address, local_user['id']))
			else:
				# External delivery - will queue it after creating email
				pass
		
		# Determine recipient_id for sent email: first local recipient or NULL
		recipient_id = local_recipients[0][1] if local_recipients else None
		
		# Store in emails table (in Sent folder) with recipient_id
		cursor.execute(
			'''INSERT INTO emails 
			   (sender_id, recipient_id, folder_id, subject, body, body_html, raw_email, headers, created_at, is_read)
			   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
			   RETURNING id''',
			(sender_id, recipient_id, sent_folder_id, subject, body, body_html, raw_email_str, headers_str, 
			 datetime.now(timezone.utc), True)  # Mark as read since user sent it
		)
		email_id = cursor.fetchone()['id']
		
		# Queue external recipients
		for to_address in to_addresses:
			domain = to_address.split('@')[-1].lower()
			
			# Check if this is a local domain (already did this above, but needed for domain)
			cursor.execute('SELECT id FROM users WHERE email = %s AND is_local = TRUE', (to_address,))
			local_user = cursor.fetchone()
			
			if not local_user:
				# External delivery - queue it
				cursor.execute(
					'''INSERT INTO outbound_queue
					   (email_id, recipient_email, recipient_domain, status, created_at)
					   VALUES (%s, %s, %s, %s, %s)
					   RETURNING id''',
					(email_id, to_address, domain, 'pending', datetime.now(timezone.utc))
				)
				queue_id = cursor.fetchone()['id']
				queue_ids.append(queue_id)
				logger.info(f"Queued email {email_id} for delivery to {to_address}")
		
		# Handle local recipients
		for to_address, recipient_id in local_recipients:
			# Skip creating Inbox copy when sender is the same as recipient
			if recipient_id == sender_id:
				continue

			# Get recipient's inbox
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

			# Copy email to recipient's inbox
			cursor.execute(
				'''INSERT INTO emails 
				   (sender_id, recipient_id, source_email_id, folder_id, subject, body, body_html, raw_email, headers, created_at, is_read)
				   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
				   RETURNING id''',
				(sender_id, recipient_id, email_id, inbox['id'], subject, body, body_html, raw_email_str, headers_str,
				 datetime.now(timezone.utc), False)
			)
			recipient_email_id = cursor.fetchone()['id']
			
			# Add recipient entry
			cursor.execute(
				'''INSERT INTO email_recipients (email_id, user_id, recipient_type)
				   VALUES (%s, %s, %s)''',
				(recipient_email_id, recipient_id, 'to')
			)
			
			logger.info(f"Stored local copy of email {email_id} for {to_address}")
		
		# Add sender as recipient for the sent email
		cursor.execute(
			'''INSERT INTO email_recipients (email_id, user_id, recipient_type)
			   VALUES (%s, %s, %s)''',
			(email_id, sender_id, 'to')
		)
		
		conn.commit()
		logger.info(f"Successfully queued email {email_id} with {len(queue_ids)} external recipients")
		return email_id, queue_ids
		
	except Exception as e:
		conn.rollback()
		logger.error(f"Error queuing outbound email: {e}")
		raise
	finally:
		cursor.close()
		conn.close()


def get_delivery_status(email_id: int) -> Dict:
	"""Get delivery status for an email."""
	conn = get_db_connection()
	cursor = conn.cursor()
	
	try:
		cursor.execute(
			'''SELECT id, recipient_email, status, attempt_count, 
			   last_attempt, delivered_at, error_message
			   FROM outbound_queue
			   WHERE email_id = %s''',
			(email_id,)
		)
		queue_entries = cursor.fetchall()
		
		cursor.execute(
			'''SELECT event_type, smtp_response, error_message, 
			   remote_server, created_at
			   FROM delivery_logs
			   WHERE email_id = %s
			   ORDER BY created_at DESC''',
			(email_id,)
		)
		logs = cursor.fetchall()
		
		return {
			'queue_entries': [
				{
					'id': entry['id'],
					'recipient': entry['recipient_email'],
					'status': entry['status'],
					'attempts': entry['attempt_count'],
					'last_attempt': entry['last_attempt'],
					'delivered_at': entry['delivered_at'],
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
					'timestamp': log['created_at']
				}
				for log in logs
			]
		}
	finally:
		cursor.close()
		conn.close()


def log_delivery_attempt(
	queue_id: int,
	email_id: int,
	recipient: str,
	event_type: str,
	smtp_response: Optional[str] = None,
	error_message: Optional[str] = None,
	remote_server: Optional[str] = None
):
	"""Log a delivery attempt."""
	conn = get_db_connection()
	cursor = conn.cursor()
	
	try:
		cursor.execute(
			'''INSERT INTO delivery_logs
			   (outbound_queue_id, email_id, recipient_email, event_type,
			    smtp_response, error_message, remote_server, created_at)
			   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''',
			(queue_id, email_id, recipient, event_type, smtp_response,
			 error_message, remote_server, datetime.now(timezone.utc))
		)
		conn.commit()
	finally:
		cursor.close()
		conn.close()
