"""
Outbound Email Storage Module

Handles queuing outgoing emails and tracking delivery status.
"""

import logging
import uuid as _uuid
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
from email.message import EmailMessage

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import get_db_connection
from app.utils.emails import (
    compute_thread_id,
    extract_threading_headers,
    normalize_subject,
)

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
	headers: Optional[Dict] = None,
	cc_addresses: Optional[List[str]] = None,
	message_id: Optional[str] = None,
	in_reply_to: Optional[str] = None,
	references: Optional[str] = None,
) -> Tuple[int, List[int]]:
	"""
	Queue an email for outbound delivery.

	Args:
		sender_id: User ID of the sender
		from_address: Sender email address
		to_addresses: List of primary recipient email addresses
		subject: Email subject
		body: Email body
		message: Complete EmailMessage object
		headers: Optional additional headers
		cc_addresses: Optional list of CC recipient email addresses
		message_id: Optional Message-ID for threading (no angle brackets).
			If None, generated from `<uuid>@<from-domain>`.
		in_reply_to: Optional In-Reply-To Message-ID (no angle brackets).
		references: Optional space-separated References chain.

	Returns:
		Tuple of (email_id, list_of_queue_ids)
	"""
	from smtp_server.email_storage import extract_bodies

	cc_addresses = cc_addresses or []

	# --- Resolve threading headers (caller-supplied > parsed from message) ---
	# Pull existing values from the EmailMessage if the caller didn't pass them.
	if not message_id:
		existing = message.get('Message-ID', '') if message is not None else ''
		if existing:
			message_id = existing.strip().lstrip('<').rstrip('>')
	if not message_id:
		domain = from_address.split('@')[-1].lower() if '@' in from_address else 'localhost'
		message_id = f"{_uuid.uuid4()}@{domain}"
	if message is not None:
		# Replace any existing Message-ID; Python's EmailMessage raises
		# ValueError if you assign Message-ID twice.
		if 'Message-ID' in message:
			del message['Message-ID']
		message['Message-ID'] = f"<{message_id}>"

	if not in_reply_to and message is not None:
		existing = message.get('In-Reply-To', '')
		if existing:
			in_reply_to = existing.strip().lstrip('<').rstrip('>')
	if in_reply_to and message is not None:
		if 'In-Reply-To' in message:
			del message['In-Reply-To']
		message['In-Reply-To'] = f"<{in_reply_to}>"

	if not references and message is not None:
		existing = message.get('References', '')
		if existing:
			refs_parts = []
			for part in existing.split():
				p = part.strip().lstrip('<').rstrip('>')
				if p:
					refs_parts.append(p)
			if refs_parts:
				references = ' '.join(refs_parts)
	if references and message is not None:
		if 'References' in message:
			del message['References']
		message['References'] = ' '.join(f"<{r}>" for r in references.split())

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

		# First pass: identify local vs external recipients across all recipients
		all_recipients = [
			(addr, 'to') for addr in to_addresses
		] + [
			(addr, 'cc') for addr in cc_addresses
		]
		# Deduplicate while preserving recipient_type priority: 'to' over 'cc'
		seen = {}
		for addr, rtype in all_recipients:
			key = addr.lower()
			if key not in seen or rtype == 'to':
				seen[key] = rtype
		unique_recipients = list(seen.items())

		queue_ids = []
		local_recipients = []

		for to_address, recipient_type in unique_recipients:
			# Check if this is a local user
			cursor.execute('SELECT id FROM users WHERE email = %s AND is_local = TRUE', (to_address,))
			local_user = cursor.fetchone()

			if local_user:
				local_recipients.append((to_address, local_user['id'], recipient_type))
			else:
				# External - queue after creating email
				pass

		# Determine recipient_id for sent email: first local 'to' recipient or NULL
		recipient_id = None
		for _, rid, rtype in local_recipients:
			if rtype == 'to':
				recipient_id = rid
				break

		# Compute thread_id once - shared across Sent row and every Inbox copy
		# (per coding_agent/plan_threading.md D2).
		subj_norm = normalize_subject(subject)
		thread_id, _strategy = compute_thread_id(
			cursor,
			message_id=message_id,
			in_reply_to=in_reply_to,
			references_chain=references,
			candidate_root_id=None,
			subject_normalized=subj_norm,
		)
		# Only populate subject_normalized when we actually used the subject
		# fallback bucket (no headers were available to thread by).
		subject_normalized_value = subj_norm if subj_norm and not (message_id or in_reply_to or references) else None

		# Store in emails table (in Sent folder) with recipient_id
		cursor.execute(
			'''INSERT INTO emails
			   (sender_id, recipient_id, folder_id, subject, body, body_html, raw_email, headers, created_at, is_read,
			    message_id, in_reply_to, references_chain, thread_id, subject_normalized)
			   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
			           %s, %s, %s, %s, %s)
			   RETURNING id''',
			(sender_id, recipient_id, sent_folder_id, subject, body, body_html, raw_email_str, headers_str,
			 datetime.now(timezone.utc), True,  # Mark as read since user sent it
			 message_id, in_reply_to, references, thread_id, subject_normalized_value)
		)
		email_id = cursor.fetchone()['id']

		# Queue external recipients (preserve recipient_type for delivery semantics)
		for to_address, recipient_type in unique_recipients:
			cursor.execute('SELECT id FROM users WHERE email = %s AND is_local = TRUE', (to_address,))
			local_user = cursor.fetchone()

			if not local_user:
				domain = to_address.split('@')[-1].lower()
				cursor.execute(
					'''INSERT INTO outbound_queue
					   (email_id, recipient_email, recipient_domain, status, created_at)
					   VALUES (%s, %s, %s, %s, %s)
					   RETURNING id''',
					(email_id, to_address, domain, 'pending', datetime.now(timezone.utc))
				)
				queue_id = cursor.fetchone()['id']
				queue_ids.append(queue_id)
				logger.info(f"Queued email {email_id} for delivery to {to_address} ({recipient_type})")

		# Handle local recipients (Inbox copies + email_recipients rows)
		for to_address, recipient_id_local, recipient_type in local_recipients:
			if recipient_id_local == sender_id:
				# Sender self-send; record as 'to'/'cc' against the sent email only
				cursor.execute(
					'''INSERT INTO email_recipients (email_id, user_id, recipient_type)
					   VALUES (%s, %s, %s)''',
					(email_id, recipient_id_local, recipient_type)
				)
				continue

			# Get recipient's inbox
			cursor.execute(
				'SELECT id FROM folders WHERE user_id = %s AND name = %s',
				(recipient_id_local, 'Inbox')
			)
			inbox = cursor.fetchone()

			if not inbox:
				cursor.execute(
					'INSERT INTO folders (user_id, name) VALUES (%s, %s) RETURNING id',
					(recipient_id_local, 'Inbox')
				)
				inbox = cursor.fetchone()

			# Copy email to recipient's inbox - shares message_id + thread_id with the
		# Sent row so a reply from the Inbox continues the same chain.
			cursor.execute(
				'''INSERT INTO emails
				   (sender_id, recipient_id, source_email_id, folder_id, subject, body, body_html, raw_email, headers, created_at, is_read,
				    message_id, in_reply_to, references_chain, thread_id, subject_normalized)
				   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
				           %s, %s, %s, %s, %s)
				   RETURNING id''',
				(sender_id, recipient_id_local, email_id, inbox['id'], subject, body, body_html, raw_email_str, headers_str,
				 datetime.now(timezone.utc), False,
				 message_id, in_reply_to, references, thread_id, subject_normalized_value)
			)
			recipient_email_id = cursor.fetchone()['id']

			# Add recipient entry (type preserved)
			cursor.execute(
				'''INSERT INTO email_recipients (email_id, user_id, recipient_type)
				   VALUES (%s, %s, %s)''',
				(recipient_email_id, recipient_id_local, recipient_type)
			)

			logger.info(f"Stored local copy of email {email_id} for {to_address} ({recipient_type})")

		# Record sender as a recipient against the sent email (type='to')
		cursor.execute(
			'''INSERT INTO email_recipients (email_id, user_id, recipient_type)
			   VALUES (%s, %s, %s)''',
			(email_id, sender_id, 'to')
		)

		conn.commit()
		logger.info(f"Successfully queued email {email_id} with {len(queue_ids)} external recipients ({len(cc_addresses)} cc)")
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
