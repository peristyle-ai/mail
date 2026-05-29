"""
Outbound Queue Processor

Background processor that delivers queued emails to external servers.
"""

import threading
import time
import logging
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Optional, List

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import get_db_connection, ensure_domains_table
from .mx_lookup import MXLookup
from .delivery import OutboundSMTPSender
from .smtp2go_delivery import SMTP2GODelivery
from .storage import log_delivery_attempt
from .rate_limiter import OutboundRateLimiter
from .dkim_signer import load_dkim_config, load_multi_domain_dkim

logger = logging.getLogger(__name__)


class OutboundQueueProcessor:
	"""Background processor for outbound email queue."""
	
	def __init__(
		self,
		check_interval: int = 30,
		max_retries: int = 5,
		retry_delays: Optional[List[int]] = None
	):
		self.check_interval = check_interval
		self.max_retries = max_retries
		self.retry_delays = retry_delays or [300, 900, 1800, 3600, 7200]
		# 5min, 15min, 30min, 1hr, 2hr
		
		self.running = False
		self.thread: Optional[threading.Thread] = None
		ensure_domains_table()
		self.mx_lookup = MXLookup()
		self.sender = OutboundSMTPSender()
		self.rate_limiter = OutboundRateLimiter()
		self.dkim_signer = load_dkim_config()
		self.dkim_signers = load_multi_domain_dkim()
		if self.dkim_signers:
			logger.info(f"DKIM signing enabled for domains: {list(self.dkim_signers.keys())}")
		elif self.dkim_signer:
			logger.info(f"DKIM signing enabled for domain: {self.dkim_signer.domain}")
		else:
			logger.warning("DKIM signing not configured")
		
		logger.info(
			f"Outbound queue processor initialized: "
			f"interval={check_interval}s, max_retries={max_retries}"
		)

	def _get_domain_relay_config(self, from_address: str):
		"""Load relay configuration for the sender's domain."""
		if '@' not in from_address:
			return None

		sender_domain = from_address.split('@', 1)[1].lower()
		conn = get_db_connection()
		cursor = conn.cursor()
		try:
			cursor.execute(
				'''SELECT domain, relay_provider, relay_host, relay_port,
				   relay_username, relay_password_encrypted, relay_from_address,
				   relay_verified
				   FROM domains
				   WHERE domain = %s AND relay_provider IS NOT NULL''',
				(sender_domain,)
			)
			return cursor.fetchone()
		finally:
			cursor.close()
			conn.close()
	
	def start(self):
		"""Start the background processing thread."""
		if self.running:
			logger.warning("Queue processor already running")
			return
		
		self.running = True
		self.thread = threading.Thread(target=self._process_loop, daemon=True)
		self.thread.start()
		logger.info("Outbound queue processor started")
	
	def stop(self):
		"""Stop the background processing thread."""
		self.running = False
		if self.thread and self.thread.is_alive():
			self.thread.join(timeout=5)
			logger.info("Outbound queue processor stopped")
	
	def _process_loop(self):
		"""Main processing loop."""
		logger.info("Queue processor loop started")
		while self.running:
			try:
				self._process_pending_emails()
			except Exception as e:
				logger.error(f"Error in processing loop: {e}")
				import traceback
				logger.error(traceback.format_exc())
			
			time.sleep(self.check_interval)
		logger.info("Queue processor loop stopped")
	
	def _process_pending_emails(self):
		"""Process all pending emails in the queue."""
		conn = get_db_connection()
		cursor = conn.cursor()
		
		try:
			# Get pending emails that are ready to send
			# Also include 'sending' emails that have been stuck for > 5 minutes (crashed/restarted during send)
			cursor.execute(
				'''SELECT id, email_id, recipient_email, recipient_domain, 
				   attempt_count
				   FROM outbound_queue
				   WHERE (
				       status IN ('pending', 'retry')
				       AND (next_attempt IS NULL OR next_attempt <= %s)
				   ) OR (
				       status = 'sending'
				       AND last_attempt < %s
				   )
				   LIMIT 10''',
				(
					datetime.now(timezone.utc),
					datetime.now(timezone.utc) - timedelta(minutes=5)
				)
			)
			pending = cursor.fetchall()
			
			if pending:
				logger.info(f"Processing {len(pending)} pending outbound emails")
			
			for row in pending:
				try:
					self._process_email(
						row['id'],
						row['email_id'],
						row['recipient_email'],
						row['recipient_domain'],
						row['attempt_count']
					)
				except Exception as e:
					logger.error(f"Error processing queue item {row['id']}: {e}")
			
		finally:
			cursor.close()
			conn.close()
	
	def _process_email(
		self,
		queue_id: int,
		email_id: int,
		recipient: str,
		domain: str,
		attempt_count: int
	):
		"""Process a single outbound email."""
		conn = get_db_connection()
		cursor = conn.cursor()
		
		try:
			# Check rate limits
			allowed, message = self.rate_limiter.check_rate_limit(domain)
			if not allowed:
				logger.warning(f"Rate limit hit for {domain}: {message}")
				cursor.execute(
					'''UPDATE outbound_queue 
					   SET status = 'retry', 
					       next_attempt = %s,
					       error_message = %s
					   WHERE id = %s''',
					(datetime.now(timezone.utc) + timedelta(minutes=5),
					 message, queue_id)
				)
				conn.commit()
				return
			
			# Update status to sending
			now = datetime.now(timezone.utc)
			cursor.execute(
				'''UPDATE outbound_queue 
				   SET status = 'sending', 
				       attempt_count = attempt_count + 1,
				       last_attempt = %s
				   WHERE id = %s''',
				(now, queue_id)
			)
			conn.commit()
			
			# Get email content
			cursor.execute(
				'''SELECT sender_id, subject, body, headers 
				   FROM emails WHERE id = %s''',
				(email_id,)
			)
			email_row = cursor.fetchone()
			
			if not email_row:
				logger.error(f"Email {email_id} not found")
				cursor.execute(
					'''UPDATE outbound_queue 
					   SET status = 'failed', error_message = %s
					   WHERE id = %s''',
					('Original email not found', queue_id)
				)
				conn.commit()
				return
			
			# Get sender's email address
			cursor.execute(
				'SELECT email FROM users WHERE id = %s',
				(email_row['sender_id'],)
			)
			sender_row = cursor.fetchone()
			if not sender_row:
				logger.error(f"Sender {email_row['sender_id']} not found")
				cursor.execute(
					'''UPDATE outbound_queue 
					   SET status = 'failed', error_message = %s
					   WHERE id = %s''',
					('Sender not found', queue_id)
				)
				conn.commit()
				return
			
			from_address = sender_row['email']
			relay_config = self._get_domain_relay_config(from_address)
			use_relay = bool(
				relay_config and relay_config['relay_username'] and
				relay_config['relay_password_encrypted'] and relay_config['relay_verified']
			)

			server_host = None
			server_port = None
			delivery_target = None
			if use_relay:
				server_host = relay_config['relay_host'] or 'mail-au.smtp2go.com'
				server_port = relay_config['relay_port'] or 2525
				delivery_target = f"{server_host}:{server_port}"
				logger.info(
					f"Using {relay_config['relay_provider']} relay for {from_address} via {delivery_target}"
				)
			else:
				if relay_config and not relay_config['relay_verified']:
					logger.info(
						f"Relay configured for {from_address} but not verified; falling back to direct MX"
					)
				mail_server = self.mx_lookup.get_mail_server(recipient)
				if not mail_server:
					error_msg = f"No mail server found for {domain}"
					logger.error(error_msg)
					cursor.execute(
						'''UPDATE outbound_queue 
						   SET status = 'failed', error_message = %s
						   WHERE id = %s''',
						(error_msg, queue_id)
					)
					conn.commit()
					log_delivery_attempt(
						queue_id, email_id, recipient, 'failure',
						None, error_msg, None
					)
					return

				server_host, server_port = mail_server
				delivery_target = f"{server_host}:{server_port}"
			
			# Build email message
			import uuid
			import re
			from email import message_from_string
			
			body = email_row['body'] or ''
			
			# Check if body is already a complete MIME message
			# If it starts with "Content-Type:", it's likely a MIME message
			if body.strip().startswith('Content-Type:'):
				# Parse the stored MIME content
				logger.info(f"Using stored MIME content for email {email_id}")
				try:
					msg = message_from_string(body)
					
					# Update From header (use del + add since replace_header may fail)
					if msg.get('From'):
						del msg['From']
					msg['From'] = from_address
					
					# Update To header
					if msg.get('To'):
						del msg['To']
					msg['To'] = recipient
					
					# Update Message-ID if needed
					if msg.get('Message-ID'):
						del msg['Message-ID']
					domain = from_address.split('@')[-1]
					msg['Message-ID'] = f"<{uuid.uuid4().hex}@{domain}>"
					
					logger.info(f"Successfully parsed MIME for email {email_id}, is_multipart={msg.is_multipart()}")
				except Exception as e:
					logger.warning(f"Failed to parse MIME content for email {email_id}: {e}, rebuilding message")
					# Fall back to rebuilding the message
					msg = EmailMessage()
					msg['From'] = from_address
					msg['To'] = recipient
					msg['Subject'] = email_row['subject']
					domain = from_address.split('@')[-1]
					msg['Message-ID'] = f"<{uuid.uuid4().hex}@{domain}>"
					html_pattern = re.compile(r'<(html|head|body|div|span|p|a|img|table|tr|td|th|h[1-6]|br|hr|style|script)', re.IGNORECASE)
					if html_pattern.search(body):
						msg.set_content(body, subtype='html', charset='utf-8')
					else:
						msg.set_content(body)
			else:
				# Rebuild the message (existing behavior for plain text)
				msg = EmailMessage()
				msg['From'] = from_address
				msg['To'] = recipient
				msg['Subject'] = email_row['subject']
				
				# Generate Message-ID (required by Gmail)
				domain = from_address.split('@')[-1]
				msg_id = f"<{uuid.uuid4().hex}@{domain}>"
				msg['Message-ID'] = msg_id
				
				# Detect if content is HTML and set appropriate content type
				html_pattern = re.compile(r'<(html|head|body|div|span|p|a|img|table|tr|td|th|h[1-6]|br|hr|style|script)', re.IGNORECASE)
				
				if html_pattern.search(body):
					logger.info(f"Detected HTML content for email {email_id}, setting text/html content type")
					msg.set_content(body, subtype='html', charset='utf-8')
				else:
					msg.set_content(body)
				
				# Add original headers (skip content-related and address headers)
				if email_row['headers']:
					skip_headers = {'from', 'to', 'subject', 'message-id', 'date', 'content-type', 'content-transfer-encoding', 'mime-version', 'content-disposition'}
					for line in email_row['headers'].split('\n'):
						if ':' in line:
							key, value = line.split(':', 1)
							header_lower = key.strip().lower()
							if header_lower not in skip_headers and not header_lower.startswith('content-'):
								msg[key.strip()] = value.strip()
			
			# ── Attach files from attachments table ────────────────────────────
			cursor.execute(
				'SELECT file_name, file_path, content_type FROM attachments WHERE email_id = %s',
				(email_id,)
			)
			attachments = cursor.fetchall()
			
			if attachments:
				logger.info(f"Found {len(attachments)} attachment(s) for email {email_id}")
			
			for att in attachments:
				att_path = att['file_path']
				if not att_path:
					continue
				if not os.path.isfile(att_path):
					logger.warning(f"Attachment file not found: {att_path}, skipping")
					continue
				
				try:
					with open(att_path, 'rb') as f:
						file_data = f.read()
					maintype = (att['content_type'] or 'application/octet-stream').split('/')[0]
					subtype = (att['content_type'] or 'application/octet-stream').split('/')[-1]
					msg.add_attachment(
						file_data,
						maintype=maintype,
						subtype=subtype,
						filename=att['file_name']
					)
					logger.info(f"Attached {att['file_name']} ({len(file_data)} bytes) to email {email_id}")
				except Exception as e:
					logger.error(f"Failed to attach {att['file_name']} for email {email_id}: {e}")
			
			# Sign with DKIM if configured (multi-domain aware)
			signing_domain = from_address.split('@')[-1] if '@' in from_address else None
			dkim_signer = None
			if signing_domain and signing_domain in self.dkim_signers:
				dkim_signer = self.dkim_signers[signing_domain]
			elif self.dkim_signer:
				dkim_signer = self.dkim_signer
			
			if dkim_signer:
				msg = dkim_signer.sign_email(msg)
				logger.debug(f"DKIM signed email for {recipient} using domain {dkim_signer.domain}")
			
			# Record rate limit
			self.rate_limiter.record_send(domain)
			
			# Attempt delivery
			log_delivery_attempt(
				queue_id, email_id, recipient, 'attempt',
				None, None, delivery_target
			)

			if use_relay:
				relay_sender = SMTP2GODelivery(
					relay_host=server_host,
					relay_port=server_port,
					username=relay_config['relay_username'],
					password=relay_config['relay_password_encrypted']
				)
				success, message = relay_sender.deliver(from_address, [recipient], msg)
			else:
				success, message = self.sender.deliver_email(
					from_address, recipient, msg, server_host, server_port
				)
			
			if success:
				# Mark as sent
				cursor.execute(
					'''UPDATE outbound_queue 
					   SET status = 'sent', 
					       delivered_at = %s,
					       error_message = NULL
					   WHERE id = %s''',
					(datetime.now(timezone.utc), queue_id)
				)
				conn.commit()
				log_delivery_attempt(
					queue_id, email_id, recipient, 'success',
					message, None, delivery_target
				)
				logger.info(f"Successfully delivered email {email_id} to {recipient}")
			else:
				# Check if temporary or permanent failure
				is_permanent = 'Permanent' in message or 'refused' in message.lower()
				
				if is_permanent or attempt_count >= self.max_retries:
					# Mark as failed
					cursor.execute(
						'''UPDATE outbound_queue 
						   SET status = 'failed', error_message = %s
						   WHERE id = %s''',
						(message[:500], queue_id)
					)
					conn.commit()
					log_delivery_attempt(
						queue_id, email_id, recipient, 'failure',
						None, message, delivery_target
					)
					logger.error(f"Failed to deliver email {email_id} to {recipient}: {message}")
				else:
					# Schedule retry
					delay = self.retry_delays[min(attempt_count, len(self.retry_delays)-1)]
					next_attempt = datetime.now(timezone.utc) + timedelta(seconds=delay)
					
					cursor.execute(
						'''UPDATE outbound_queue 
						   SET status = 'retry', 
						       next_attempt = %s,
						       error_message = %s
						   WHERE id = %s''',
						(next_attempt, message[:500], queue_id)
					)
					conn.commit()
					log_delivery_attempt(
						queue_id, email_id, recipient, 'bounce',
						None, message, delivery_target
					)
					logger.warning(
						f"Delivery failed for {recipient}, retry {attempt_count+1}/{self.max_retries} "
						f"scheduled at {next_attempt}"
					)
					
		finally:
			cursor.close()
			conn.close()
	
	def get_queue_stats(self) -> dict:
		"""Get statistics about the outbound queue."""
		conn = get_db_connection()
		cursor = conn.cursor()
		
		try:
			cursor.execute(
				'''SELECT status, COUNT(*) as count 
				   FROM outbound_queue 
				   GROUP BY status'''
			)
			status_counts = {row['status']: row['count'] for row in cursor.fetchall()}
			
			cursor.execute(
				'''SELECT COUNT(*) as count 
				   FROM outbound_queue 
				   WHERE status IN ('pending', 'retry')'''
			)
			pending = cursor.fetchone()['count']
			
			return {
				'pending': pending,
				'by_status': status_counts,
				'rate_limits': self.rate_limiter.get_stats()
			}
		finally:
			cursor.close()
			conn.close()
