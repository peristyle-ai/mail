import hashlib
import hmac
import logging
import os
import re
import time
from datetime import datetime, timezone
from email.utils import parseaddr

from flask import Blueprint, request, jsonify

from ..db import get_db_connection
from ..db import get_seed_domains
from ..utils.webhooks import verify_webhook_secret

inbound_bp = Blueprint('inbound', __name__)
logger = logging.getLogger(__name__)

LOCAL_DOMAINS = get_seed_domains() + ['localhost', 'example.com']

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


def _get_local_domains() -> set[str]:
	"""Return local domains from the domains table, falling back to defaults."""
	conn = get_db_connection()
	cursor = conn.cursor()
	try:
		cursor.execute('SELECT domain FROM domains ORDER BY domain')
		rows = cursor.fetchall()
		if rows:
			return {row['domain'] for row in rows if row.get('domain')}
		return set(LOCAL_DOMAINS)
	finally:
		cursor.close()
		conn.close()


def _get_domain_webhook_secret_hash(domain: str) -> str:
	"""Return the stored webhook secret hash for a domain, if any."""
	conn = get_db_connection()
	cursor = conn.cursor()
	try:
		cursor.execute('SELECT webhook_secret FROM domains WHERE domain = %s', (domain,))
		row = cursor.fetchone()
		if not row:
			return ''
		return row.get('webhook_secret') or ''
	finally:
		cursor.close()
		conn.close()


def _parse_inbound_payload(content_type: str):
	"""Parse inbound payload and return normalized field values."""
	if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
		sender = request.form.get("from", "") or request.form.get("from_address", "") or request.form.get("sender", "")
		recipient = request.form.get("to", "") or request.form.get("rcpt", "") or request.form.get("recipient", "")
		subject = request.form.get("subject", "") or request.form.get("subjects", "")
		text_body = request.form.get("text", "")
		html_body = request.form.get("html", "")
		sender_ip = request.form.get("sender_ip", "") or request.form.get("srchost", "")
		raw_mime = request.form.get("mail", "") or request.form.get("raw_email", "")
		if not raw_mime and request.files:
			for file_key in request.files:
				uploaded = request.files.get(file_key)
				if uploaded:
					try:
						raw_mime = uploaded.read().decode('utf-8', errors='replace')
					except Exception as e:
						logger.warning(f"Inbound: failed to read uploaded file '{file_key}': {e}")
					break
		return sender, recipient, subject, text_body, html_body, sender_ip, raw_mime, None, None

	if "application/json" in content_type:
		data = request.get_json(silent=True)
		if not data or not isinstance(data, dict):
			return '', '', '', '', '', '', '', jsonify({"error": "Invalid JSON"}), 400
		sender = data.get("from", "") or data.get("from_address", "") or data.get("sender", "")
		recipient = data.get("to", "") or data.get("rcpt", "") or data.get("recipient", "")
		subject = data.get("subject", "")
		text_body = data.get("text", data.get("body", ""))
		html_body = data.get("html", "")
		sender_ip = data.get("sender_ip", "") or data.get("srchost", "")
		raw_mime = data.get("mail", "") or data.get("raw_email", "")
		return sender, recipient, subject, text_body, html_body, sender_ip, raw_mime, None, None

	return '', '', '', '', '', '', '', jsonify({"error": "Unsupported content type"}), 400


def _verify_inbound_request(recipient_email: str, raw_body: bytes = b'') -> tuple[bool, str]:
	"""Verify inbound request using per-domain secret or legacy SMTP2GO HMAC.

	Args:
	    recipient_email: The parsed recipient email (used to look up per-domain secret).
	    raw_body: Pre-captured raw request body bytes (avoids relying on request.get_data()
	              which may return empty after form/json parsing).
	"""
	recipient_domain = recipient_email.split('@')[-1].lower() if '@' in recipient_email else ''
	domain_secret_hash = _get_domain_webhook_secret_hash(recipient_domain)
	provided_secret = request.headers.get('X-Webhook-Secret', '').strip()

	# Use the pre-captured raw body if provided; fall back to request.get_data() for safety.
	body_for_hmac = raw_body if raw_body else request.get_data()

	if domain_secret_hash:
		if provided_secret:
			if verify_webhook_secret(provided_secret, domain_secret_hash):
				return True, ''
			return False, 'Invalid webhook secret'
		if SMTP2GO_WEBHOOK_SECRET:
			signature = request.headers.get('X-SMTP2GO-Signature', '')
			if _verify_smtp2go_signature(body_for_hmac, signature):
				return True, ''
			return False, 'Invalid signature'
		return False, 'Missing webhook secret'

	if SMTP2GO_WEBHOOK_SECRET:
		signature = request.headers.get('X-SMTP2GO-Signature', '')
		if _verify_smtp2go_signature(body_for_hmac, signature):
			return True, ''
		return False, 'Invalid signature'

	return True, ''


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
	# ── Payload size limit ─────────────────────────────────────────────────────
	content_length = request.content_length or 0
	if content_length > MAX_RAW_MIME_LENGTH:
		return jsonify({"error": "Payload too large"}), 413
	if not content_length:
		raw_data = request.get_data()
		if len(raw_data) > MAX_RAW_MIME_LENGTH:
			return jsonify({"error": "Payload too large"}), 413

	# ── Capture raw body for HMAC verification ────────────────────────────────
	# IMPORTANT: This must run BEFORE any form/json parsing, because Flask's request.form
	# / request.get_json() can cause request.get_data() to return empty bytes afterward
	# (the input stream is consumed during parsing). Without this, signature verification
	# would always fail on multipart and JSON bodies.
	raw_body = request.get_data(cache=True, as_text=False, parse_form_data=False)

	content_type = request.content_type or ""
	content_length = request.content_length or 0
	logger.info(f"Inbound: content_type={content_type}, content_length={content_length}, remote_addr={client_ip}")
	if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
		form_keys = list(request.form.keys())
		form_sizes = {k: min(len(request.form.get(k, '')), 200) for k in form_keys}
		file_keys = list(request.files.keys())
		file_sizes = {}
		for fk in file_keys:
			f = request.files.get(fk)
			if f:
				f.seek(0, 2)
				file_sizes[fk] = f.tell()
				f.seek(0)
		logger.info(f"Inbound: form_keys={form_keys}, sizes={form_sizes}, files={file_keys}, file_sizes={file_sizes}")
		for key in form_keys:
			val = request.form.get(key, '')[:300]
			logger.info(f"Inbound: field '{key}' = {val}")
		for key in file_keys:
			f = request.files.get(key)
			if f:
				logger.info(f"Inbound: file '{key}' filename={f.filename}, content_type={f.content_type}")
	elif "application/json" in content_type:
		json_data = request.get_json(silent=True)
		if json_data and isinstance(json_data, dict):
			for key, val in json_data.items():
				logger.info(f"Inbound: json '{key}' = {str(val)[:300]}")
		else:
			logger.info(f"Inbound: JSON body invalid or empty")
	else:
		raw_data = request.get_data()
		logger.info(f"Inbound: unknown content type, raw_data_len={len(raw_data)}, first_500={raw_data[:500]}")

	# ── Parse payload ──────────────────────────────────────────────────────────
	parsed_payload = _parse_inbound_payload(content_type)
	sender, recipient, subject, text_body, html_body, sender_ip, raw_mime, error_response, error_status = parsed_payload
	if error_response:
		return error_response, error_status

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

	verified, verification_error = _verify_inbound_request(recipient_email, raw_body)
	if not verified:
		logger.warning(f"Inbound: verification failed for {recipient_email} from {client_ip}: {verification_error}")
		return jsonify({"error": verification_error}), 403

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
		if recipient_domain not in _get_local_domains():
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

	# ── Extract body from MIME if text/html are empty ──────────────────────────
	if raw_email_clean and not body_clean and not body_html_clean:
		try:
			import base64 as b64mod
			from email import policy
			from email.parser import BytesParser

			raw_bytes = raw_email_clean.encode('utf-8', errors='replace')

			if raw_bytes[:100].lstrip().startswith(b'Received:') or \
			   raw_bytes[:100].lstrip().startswith(b'From:') or \
			   raw_bytes[:100].lstrip().startswith(b'Return-Path:') or \
			   raw_bytes[:100].lstrip().startswith(b'Delivered-To:') or \
			   raw_bytes[:100].lstrip().startswith(b'MIME-Version:') or \
			   b'Content-Type:' in raw_bytes[:500]:
				mime_bytes = raw_bytes
			else:
				try:
					mime_bytes = b64mod.b64decode(raw_bytes)
					logger.info(f"Inbound: decoded Base64 raw_email ({len(raw_bytes)} -> {len(mime_bytes)} bytes)")
				except Exception:
					mime_bytes = raw_bytes
					logger.info(f"Inbound: raw_email not valid Base64, using as-is")

			msg = BytesParser(policy=policy.default).parsebytes(mime_bytes)

			if not body_clean:
				for part in msg.walk():
					if part.get_content_type() == 'text/plain':
						payload = part.get_payload(decode=True)
						if payload:
							charset = part.get_content_charset() or 'utf-8'
							try:
								body_clean = _sanitize_string(payload.decode(charset, errors='replace'))
							except (LookupError, UnicodeDecodeError):
								body_clean = _sanitize_string(payload.decode('utf-8', errors='replace'))
							break

			if not body_html_clean:
				for part in msg.walk():
					if part.get_content_type() == 'text/html':
						payload = part.get_payload(decode=True)
						if payload:
							charset = part.get_content_charset() or 'utf-8'
							try:
								body_html_clean = _sanitize_string(payload.decode(charset, errors='replace'))
							except (LookupError, UnicodeDecodeError):
								body_html_clean = _sanitize_string(payload.decode('utf-8', errors='replace'))
							break

			# Extract subject from MIME if ours is empty
			if not subject_clean:
				mime_subject = msg.get('Subject', '')
				if mime_subject:
					subject_clean = _sanitize_string(_strip_newlines(str(mime_subject)))[:MAX_SUBJECT_LENGTH]

			logger.info(f"Inbound: extracted body from MIME: text={len(body_clean)} html={len(body_html_clean)}")
		except Exception as e:
			logger.warning(f"Inbound: failed to extract body from MIME: {e}")

	# ── Decode Base64 raw_email for storage ──────────────────────────────────────
	if raw_email_clean:
		try:
			import base64 as b64mod
			raw_bytes_check = raw_email_clean.encode('utf-8', errors='replace')
			if not (raw_bytes_check[:100].lstrip().startswith(b'Received:') or \
			   raw_bytes_check[:100].lstrip().startswith(b'From:') or \
			   raw_bytes_check[:100].lstrip().startswith(b'Return-Path:') or \
			   raw_bytes_check[:100].lstrip().startswith(b'Delivered-To:') or \
			   raw_bytes_check[:100].lstrip().startswith(b'MIME-Version:') or \
			   b'Content-Type:' in raw_bytes_check[:500]):
				decoded = b64mod.b64decode(raw_bytes_check)
				raw_email_clean = _sanitize_string(decoded.decode('utf-8', errors='replace'))
				logger.info(f"Inbound: decoded Base64 raw_email for storage ({len(raw_bytes_check)} -> {len(decoded)} bytes)")
		except Exception:
			pass

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
				import base64 as b64mod
				from email import policy
				from email.parser import BytesParser
				import uuid
				import os

				UPLOADS_DIR = os.path.join(
					os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'uploads'
				)
				os.makedirs(UPLOADS_DIR, exist_ok=True)

				raw_bytes = raw_mime.encode('utf-8', errors='replace')

				# Decode Base64 if the raw_email was Base64-encoded
				if raw_bytes[:100].lstrip().startswith(b'Received:') or \
				   raw_bytes[:100].lstrip().startswith(b'From:') or \
				   raw_bytes[:100].lstrip().startswith(b'Return-Path:') or \
				   raw_bytes[:100].lstrip().startswith(b'Delivered-To:') or \
				   raw_bytes[:100].lstrip().startswith(b'MIME-Version:') or \
				   b'Content-Type:' in raw_bytes[:500]:
					mime_bytes = raw_bytes
				else:
					try:
						mime_bytes = b64mod.b64decode(raw_bytes)
					except Exception:
						mime_bytes = raw_bytes

				msg = BytesParser(policy=policy.default).parsebytes(mime_bytes)

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
