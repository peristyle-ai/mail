import logging
import re
from datetime import datetime, timezone
from email.utils import parseaddr

from flask import Blueprint, request, jsonify

from ..db import get_db_connection

inbound_bp = Blueprint('inbound', __name__)
logger = logging.getLogger(__name__)

LOCAL_DOMAINS = [
	'example.com.au', 'mailrelay.com', 'example.ai',
	'example.ai', 'example.io', 'localhost', 'example.com',
]


def extract_email(address: str) -> str:
	"""Extract email address from 'Name <email@domain.com>' or plain email."""
	parsed = parseaddr(address)
	if parsed[1]:
		return parsed[1].lower().strip()
	return address.lower().strip()


def is_sender_blocked(sender_email: str) -> bool:
	"""Check if sender email or domain is in the blocklist."""
	domain = sender_email.split('@')[-1] if '@' in sender_email else ''
	conn = get_db_connection()
	cursor = conn.cursor()
	try:
		cursor.execute(
			'''SELECT id FROM sender_blocklist
			   WHERE email = %s OR (domain = %s AND email IS NULL)
			   LIMIT 1''',
			(sender_email, domain)
		)
		row = cursor.fetchone()
		return row is not None
	finally:
		cursor.close()
		conn.close()


def resolve_recipient_user(recipient_email: str):
	"""Look up local user by email. Returns (user_id, is_local) or None."""
	conn = get_db_connection()
	cursor = conn.cursor()
	try:
		cursor.execute(
			'SELECT id, is_local FROM users WHERE email = %s',
			(recipient_email,)
		)
		row = cursor.fetchone()
		if row and row['is_local']:
			return row['id'], True
		return None
	finally:
		cursor.close()
		conn.close()


def find_or_create_sender(sender_email: str) -> int:
	"""Find or create a user record for the sender. Returns user_id."""
	conn = get_db_connection()
	cursor = conn.cursor()
	try:
		cursor.execute('SELECT id FROM users WHERE email = %s', (sender_email,))
		row = cursor.fetchone()
		if row:
			return row['id']

		sender_username = sender_email.split('@')[0] if '@' in sender_email else 'unknown'
		cursor.execute(
			'''INSERT INTO users (email, password_hash, name, is_local, created_at)
			   VALUES (%s, %s, %s, %s, %s) RETURNING id''',
			(sender_email, 'external_sender', sender_username, False, datetime.now(timezone.utc))
		)
		conn.commit()
		return cursor.fetchone()['id']
	finally:
		cursor.close()
		conn.close()


def get_or_create_inbox(user_id: int) -> int:
	"""Get or create Inbox folder for a user. Returns folder_id."""
	conn = get_db_connection()
	cursor = conn.cursor()
	try:
		cursor.execute(
			'SELECT id FROM folders WHERE user_id = %s AND name = %s',
			(user_id, 'Inbox')
		)
		folder = cursor.fetchone()
		if folder:
			return folder['id']

		cursor.execute(
			'INSERT INTO folders (user_id, name) VALUES (%s, %s) RETURNING id',
			(user_id, 'Inbox')
		)
		conn.commit()
		return cursor.fetchone()['id']
	finally:
		cursor.close()
		conn.close()


@inbound_bp.route('/inbound', methods=['POST'])
def receive_inbound_webhook():
	"""
	Receive inbound email webhook from SMTP2GO (or similar services).

	No JWT auth required - this endpoint is called by relay services.
	Accepts application/x-www-form-urlencoded, multipart/form-data, or JSON.

	Form fields:
		from:     sender email address
		to:       recipient email address
		subject:  email subject
		text:     plain text body (optional)
		html:     HTML body (optional)
		sender_ip: sender's IP address (optional)
		mail:     raw MIME content (optional, for attachment extraction)
	"""
	content_type = request.content_type or ""

	# ── Parse payload ──────────────────────────────────────────────────────────
	if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
		sender = request.form.get("from", "")
		recipient = request.form.get("to", "")
		subject = request.form.get("subject", "")
		text_body = request.form.get("text", "")
		html_body = request.form.get("html", "")
		sender_ip = request.form.get("sender_ip", "")
		raw_mime = request.form.get("mail", "")
	elif "application/json" in content_type:
		data = request.get_json(silent=True) or {}
		sender = data.get("from", "")
		recipient = data.get("to", "")
		subject = data.get("subject", "")
		text_body = data.get("text", data.get("body", ""))
		html_body = data.get("html", "")
		sender_ip = data.get("sender_ip", "")
		raw_mime = data.get("mail", "")
	else:
		return jsonify({"error": "Unsupported content type"}), 400

	logger.info(f"Inbound webhook: from={sender} to={recipient} subject={subject}")

	# ── Validation ─────────────────────────────────────────────────────────────
	if not sender or not recipient:
		return jsonify({"error": "Missing sender or recipient"}), 400

	sender_email = extract_email(sender)
	recipient_email = extract_email(recipient)

	if not sender_email or '@' not in sender_email:
		return jsonify({"error": "Invalid sender email"}), 400
	if not recipient_email or '@' not in recipient_email:
		return jsonify({"error": "Invalid recipient email"}), 400

	# ── Sender blocklist check ──────────────────────────────────────────────────
	if is_sender_blocked(sender_email):
		logger.info(f"Inbound: blocked sender {sender_email}")
		return jsonify({"status": "blocked"}), 200

	# ── Resolve recipient ──────────────────────────────────────────────────────
	result = resolve_recipient_user(recipient_email)
	if not result:
		recipient_domain = recipient_email.split('@')[-1].lower() if '@' in recipient_email else ''
		if recipient_domain not in LOCAL_DOMAINS:
			logger.info(f"Inbound: unknown recipient domain {recipient_email}")
			return jsonify({"status": "rejected", "reason": "unknown recipient"}), 200
		return jsonify({"status": "rejected", "reason": "unknown recipient"}), 200

	recipient_id = result[0]

	# ── Find or create sender ──────────────────────────────────────────────────
	sender_id = find_or_create_sender(sender_email)

	# ── Get recipient's Inbox folder ────────────────────────────────────────────
	inbox_id = get_or_create_inbox(recipient_id)

	# ── Build headers string ────────────────────────────────────────────────────
	headers_str = f"from: {sender_email}\nto: {recipient_email}\n"
	if subject:
		headers_str += f"subject: {subject}\n"
	if sender_ip:
		headers_str += f"x-sender-ip: {sender_ip}\n"
	headers_str += f"x-received-via: inbound-webhook\n"

	# ── Sanitize strings for PostgreSQL ─────────────────────────────────────────
	def sanitize(s):
		if s is None:
			return ''
		return s.replace('\x00', '')

	subject_clean = sanitize(subject)
	body_clean = sanitize(text_body)
	body_html_clean = sanitize(html_body)
	headers_clean = sanitize(headers_str)
	raw_email_clean = sanitize(raw_mime)

	# ── Store the email ─────────────────────────────────────────────────────────
	conn = get_db_connection()
	cursor = conn.cursor()
	try:
		cursor.execute(
			'''INSERT INTO emails
			   (sender_id, recipient_id, folder_id, subject, body, body_html,
			    raw_email, headers, created_at, is_read)
			   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
			   RETURNING id''',
			(sender_id, recipient_id, inbox_id, subject_clean, body_clean,
			 body_html_clean, raw_email_clean, headers_clean,
			 datetime.now(timezone.utc), False)
		)
		email_id = cursor.fetchone()['id']

		# Add recipient entry
		cursor.execute(
			'INSERT INTO email_recipients (email_id, user_id, recipient_type) VALUES (%s, %s, %s)',
			(email_id, recipient_id, 'to')
		)

		# Process attachments from raw MIME if present
		if raw_mime:
			try:
				from email import policy
				from email.parser import BytesParser
				import uuid
				import os

				UPLOADS_DIR = os.path.join(
					os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'uploads'
				)
				os.makedirs(UPLOADS_DIR, exist_ok=True)

				raw_bytes = raw_mime.encode('utf-8', errors='replace')
				msg = BytesParser(policy=policy.default).parsebytes(raw_bytes)

				for part in msg.walk():
					content_disposition = part.get('Content-Disposition', '')
					content_id = part.get('Content-ID', '')
					is_attachment = 'attachment' in content_disposition
					is_inline_image = ('inline' in content_disposition and content_id) or \
						(part.get_content_maintype() == 'image' and content_id)
					if not is_attachment and not is_inline_image:
						continue
					if part.get_content_maintype() == 'multipart':
						continue

					filename = part.get_filename()
					if not filename:
						filename = f"attachment_{uuid.uuid4().hex[:8]}.bin"

					content_type = part.get_content_type()
					data = part.get_payload(decode=True)
					if not data:
						continue
					file_size = len(data)

					unique_filename = str(uuid.uuid4())
					ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
					if ext:
						unique_filename += '.' + ext
					file_path = os.path.join(UPLOADS_DIR, unique_filename)

					with open(file_path, 'wb') as f:
						f.write(data)

					cursor.execute('SAVEPOINT att_save')
					try:
						cursor.execute(
							'''INSERT INTO attachments
							   (email_id, file_name, content_type, file_size, file_path)
							   VALUES (%s, %s, %s, %s, %s)''',
							(email_id, filename, content_type, file_size, file_path)
						)
						cursor.execute('RELEASE SAVEPOINT att_save')
					except Exception:
						cursor.execute('ROLLBACK TO SAVEPOINT att_save')
						if os.path.exists(file_path):
							os.remove(file_path)

			except Exception as e:
				logger.error(f"Error processing MIME attachments from inbound webhook: {e}")

		conn.commit()
		logger.info(f"Inbound webhook stored email ID {email_id} for {recipient_email}")
		return jsonify({"status": "received", "email_id": email_id}), 200

	except Exception as e:
		conn.rollback()
		logger.error(f"Error storing inbound webhook email: {e}")
		return jsonify({"error": "Internal server error"}), 500
	finally:
		cursor.close()
		conn.close()