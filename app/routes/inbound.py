import hashlib
import hmac
import logging
import re
import time
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

MAX_SUBJECT_LENGTH = 500
MAX_BODY_LENGTH = 5_000_000
MAX_RAW_MIME_LENGTH = 50_000_000
MAX_EMAIL_LENGTH = 320
MAX_SENDER_IP_LENGTH = 45
RATE_LIMIT_PER_IP = 60
RATE_LIMIT_WINDOW = 60

_inbound_rate_limits: dict = {}

SMTP2GO_WEBHOOK_SECRET = None


def _load_webhook_secret():
	global SMTP2GO_WEBHOOK_SECRET
	import os
	secret = os.environ.get('SMTP2GO_WEBHOOK_SECRET', '').strip()
	if secret:
		SMTP2GO_WEBHOOK_SECRET = secret


_load_webhook_secret()


def _sanitize_string(s: str) -> str:
	if s is None:
		return ''
	return s.replace('\x00', '')


def _strip_newlines(s: str) -> str:
	return s.replace('\r', '').replace('\n', '')


def extract_email(address: str) -> str:
	parsed = parseaddr(address)
	if parsed[1]:
		email = parsed[1].lower().strip()
	else:
		email = address.lower().strip()
	if len(email) > MAX_EMAIL_LENGTH:
		return ''
	if not re.match(r'^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$', email):
		return ''
	return email


def _validate_sender_ip(ip_str: str) -> str:
	ip_str = ip_str.strip()
	if len(ip_str) > MAX_SENDER_IP_LENGTH:
		return ''
	if not re.match(r'^[\d.:a-fA-F]+$', ip_str):
		return ''
	return ip_str


def _check_rate_limit(ip_address: str) -> bool:
	now = time.time()
	cutoff = now - RATE_LIMIT_WINDOW
	_inbound_rate_limits.setdefault(ip_address, [])
	_inbound_rate_limits[ip_address] = [
		t for t in _inbound_rate_limits[ip_address] if t > cutoff
	]
	if len(_inbound_rate_limits[ip_address]) >= RATE_LIMIT_PER_IP:
		return False
	_inbound_rate_limits[ip_address].append(now)
	return True


def _verify_smtp2go_signature(request_data: bytes, signature: str) -> bool:
	if not SMTP2GO_WEBHOOK_SECRET:
		return True
	expected = hmac.new(
		SMTP2GO_WEBHOOK_SECRET.encode('utf-8'),
		request_data,
		hashlib.sha256
	).hexdigest()
	return hmac.compare_digest(expected, signature)


def is_sender_blocked(sender_email: str) -> bool:
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
	conn = get_db_connection()
	cursor = conn.cursor()
	try:
		cursor.execute('SELECT id FROM users WHERE email = %s', (sender_email,))
		row = cursor.fetchone()
		if row:
			return row['id']

		sender_username = sender_email.split('@')[0][:100] if '@' in sender_email else 'unknown'
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
	# ── Rate limiting ──────────────────────────────────────────────────────────
	client_ip = request.remote_addr or 'unknown'
	if not _check_rate_limit(client_ip):
		logger.warning(f"Inbound rate limit exceeded for {client_ip}")
		return jsonify({"error": "Rate limit exceeded"}), 429

	# ── Optional: verify SMTP2GO signature ──────────────────────────────────────
	if SMTP2GO_WEBHOOK_SECRET:
		signature = request.headers.get('X-SMTP2GO-Signature', '')
		if not _verify_smtp2go_signature(request.get_data(), signature):
			logger.warning(f"Inbound: invalid SMTP2GO signature from {client_ip}")
			return jsonify({"error": "Invalid signature"}), 403

	# ── Payload size limit ─────────────────────────────────────────────────────
	content_length = request.content_length or 0
	if content_length > MAX_RAW_MIME_LENGTH:
		return jsonify({"error": "Payload too large"}), 413
	if not content_length:
		raw_data = request.get_data()
		if len(raw_data) > MAX_RAW_MIME_LENGTH:
			return jsonify({"error": "Payload too large"}), 413

	# ── Parse payload ──────────────────────────────────────────────────────────
	content_type = request.content_type or ""

	if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
		sender = request.form.get("from", "")
		recipient = request.form.get("to", "")
		subject = request.form.get("subject", "")
		text_body = request.form.get("text", "")
		html_body = request.form.get("html", "")
		sender_ip = request.form.get("sender_ip", "")
		raw_mime = request.form.get("mail", "")
	elif "application/json" in content_type:
		data = request.get_json(silent=True)
		if not data or not isinstance(data, dict):
			return jsonify({"error": "Invalid JSON"}), 400
		sender = data.get("from", "")
		recipient = data.get("to", "")
		subject = data.get("subject", "")
		text_body = data.get("text", data.get("body", ""))
		html_body = data.get("html", "")
		sender_ip = data.get("sender_ip", "")
		raw_mime = data.get("mail", "")
	else:
		return jsonify({"error": "Unsupported content type"}), 400

	# ── Type validation ─────────────────────────────────────────────────────────
	for field_name, val in [
		('from', sender), ('to', recipient), ('subject', subject),
		('text', text_body), ('html', html_body), ('mail', raw_mime),
	]:
		if not isinstance(val, str):
			return jsonify({"error": f"Invalid field type: {field_name}"}), 400

	sender_ip = sender_ip if isinstance(sender_ip, str) else ""

	# ── Required field validation ───────────────────────────────────────────────
	if not sender or not recipient:
		return jsonify({"error": "Missing sender or recipient"}), 400

	sender_email = extract_email(sender)
	recipient_email = extract_email(recipient)

	if not sender_email:
		return jsonify({"error": "Invalid sender email"}), 400
	if not recipient_email:
		return jsonify({"error": "Invalid recipient email"}), 400

	# ── Length limits ───────────────────────────────────────────────────────────
	subject = subject[:MAX_SUBJECT_LENGTH] if subject else subject
	text_body = text_body[:MAX_BODY_LENGTH] if text_body else text_body
	html_body = html_body[:MAX_BODY_LENGTH] if html_body else html_body
	raw_mime = raw_mime[:MAX_RAW_MIME_LENGTH] if raw_mime else raw_mime
	sender_ip = _validate_sender_ip(sender_ip)

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
		else:
			logger.info(f"Inbound: no local user for {recipient_email}")
		return jsonify({"status": "rejected", "reason": "unknown recipient"}), 200

	recipient_id = result[0]

	# ── Find or create sender ──────────────────────────────────────────────────
	sender_id = find_or_create_sender(sender_email)

	# ── Get recipient's Inbox folder ────────────────────────────────────────────
	inbox_id = get_or_create_inbox(recipient_id)

	# ── Build headers string (stripped of newlines to prevent injection) ────────
	headers_str = f"from: {_strip_newlines(sender_email)}\nto: {_strip_newlines(recipient_email)}\n"
	if subject:
		headers_str += f"subject: {_strip_newlines(subject)[:200]}\n"
	if sender_ip:
		headers_str += f"x-sender-ip: {_strip_newlines(sender_ip)}\n"
	headers_str += "x-received-via: inbound-webhook\n"

	# ── Sanitize strings for PostgreSQL ─────────────────────────────────────────
	subject_clean = _sanitize_string(subject)
	body_clean = _sanitize_string(text_body)
	body_html_clean = _sanitize_string(html_body)
	headers_clean = _sanitize_string(headers_str)
	raw_email_clean = _sanitize_string(raw_mime)

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
					filename = _sanitize_string(_strip_newlines(filename))[:255]
					if not filename:
						continue

					content_type = part.get_content_type()
					if len(content_type) > 255:
						content_type = 'application/octet-stream'

					data = part.get_payload(decode=True)
					if not data:
						continue
					file_size = len(data)

					# Skip suspiciously large individual attachments
					if file_size > 25_000_000:
						logger.warning(f"Skipping large attachment {filename} ({file_size} bytes)")
						continue

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