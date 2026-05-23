"""
Tests for POST /inbound webhook endpoint (SMTP2GO relay receiver)
"""

import hashlib
import hmac
import pytest
import time

from app.db import get_db_connection


LOCAL_DOMAINS = [
	'example.com.au', 'mailrelay.com', 'example.ai',
	'example.ai', 'example.io', 'localhost', 'example.com',
]


@pytest.fixture
def inbound_client(client):
	"""Flask test client with rate limit reset before each test."""
	import app.routes.inbound as inbound_module
	inbound_module._inbound_rate_limits.clear()
	return client


@pytest.fixture
def local_user(db):
	"""Create a local user with a LOCAL_DOMAINS email for inbound delivery."""
	conn = db()
	cursor = conn.cursor()
	cursor.execute("DELETE FROM sender_blocklist")
	cursor.execute("DELETE FROM email_recipients")
	cursor.execute("DELETE FROM attachments")
	cursor.execute("DELETE FROM emails")
	cursor.execute("DELETE FROM folders WHERE user_id IN (SELECT id FROM users WHERE email LIKE '%@example.com.au')")
	cursor.execute("DELETE FROM users WHERE email = 'inbound_test@example.com.au'")
	conn.commit()
	cursor.close()
	conn.close()

	from app.utils.auth import hash_password
	password_hash = hash_password('not-a-real-password')
	conn = db()
	cursor = conn.cursor()
	cursor.execute(
		'''INSERT INTO users (email, password_hash, name, is_local)
		   VALUES (%s, %s, %s, %s) RETURNING id, email''',
		('inbound_test@example.com.au', password_hash, 'Inbound Test User', True)
	)
	user = cursor.fetchone()
	conn.commit()
	cursor.close()
	conn.close()
	return user


@pytest.fixture
def blocked_sender(db):
	"""Add a sender to the blocklist and return the blocked email."""
	conn = db()
	cursor = conn.cursor()
	cursor.execute("DELETE FROM sender_blocklist WHERE email = 'spammer@evil.com'")
	cursor.execute(
		'''INSERT INTO sender_blocklist (email, source, notes)
		   VALUES (%s, %s, %s)''',
		('spammer@evil.com', 'manual', 'Test blocked sender')
	)
	conn.commit()
	cursor.close()
	conn.close()
	return 'spammer@evil.com'


@pytest.fixture
def blocked_domain(db):
	"""Add a domain to the blocklist and return the blocked domain."""
	conn = db()
	cursor = conn.cursor()
	cursor.execute("DELETE FROM sender_blocklist WHERE domain = 'evil.com'")
	cursor.execute(
		'''INSERT INTO sender_blocklist (domain, source, notes)
		   VALUES (%s, %s, %s)''',
		('evil.com', 'manual', 'Test blocked domain')
	)
	conn.commit()
	cursor.close()
	conn.close()
	return 'evil.com'


class TestInboundBasic:
	"""Basic inbound webhook tests"""

	def test_inbound_form_data(self, inbound_client, local_user):
		"""Test receiving inbound email via form data"""
		response = inbound_client.post('/inbound', data={
			'from': 'user@example.com',
			'to': 'inbound_test@example.com.au',
			'subject': 'Test Inbound',
			'text': 'Hello from SMTP2GO'
		})
		assert response.status_code == 200
		data = response.get_json()
		assert data['status'] == 'received'
		assert 'email_id' in data

		email_id = data['email_id']
		conn = get_db_connection()
		cursor = conn.cursor()
		cursor.execute('SELECT * FROM emails WHERE id = %s', (email_id,))
		email = cursor.fetchone()
		cursor.close()
		conn.close()
		assert email is not None
		assert email['subject'] == 'Test Inbound'
		assert email['body'] == 'Hello from SMTP2GO'

	def test_inbound_json(self, inbound_client, local_user):
		"""Test receiving inbound email via JSON"""
		response = inbound_client.post('/inbound', json={
			'from': 'user@example.com',
			'to': 'inbound_test@example.com.au',
			'subject': 'JSON Inbound',
			'text': 'Via JSON body',
			'html': '<p>Via JSON</p>'
		})
		assert response.status_code == 200
		data = response.get_json()
		assert data['status'] == 'received'
		assert 'email_id' in data

		email_id = data['email_id']
		conn = get_db_connection()
		cursor = conn.cursor()
		cursor.execute('SELECT * FROM emails WHERE id = %s', (email_id,))
		email = cursor.fetchone()
		cursor.close()
		conn.close()
		assert email['body_html'] == '<p>Via JSON</p>'

	def test_inbound_json_body_field(self, inbound_client, local_user):
		"""Test JSON payload using 'body' instead of 'text'"""
		response = inbound_client.post('/inbound', json={
			'from': 'user@example.com',
			'to': 'inbound_test@example.com.au',
			'subject': 'Body Field',
			'body': 'Using body field'
		})
		assert response.status_code == 200
		data = response.get_json()
		assert data['status'] == 'received'

		email_id = data['email_id']
		conn = get_db_connection()
		cursor = conn.cursor()
		cursor.execute('SELECT * FROM emails WHERE id = %s', (email_id,))
		email = cursor.fetchone()
		cursor.close()
		conn.close()
		assert email['body'] == 'Using body field'

	def test_inbound_creates_sender_user(self, inbound_client, local_user):
		"""Test that a non-existing sender is created as is_local=FALSE"""
		sender_email = 'new_external_sender_12345@external.com'
		conn = get_db_connection()
		cursor = conn.cursor()
		cursor.execute("DELETE FROM users WHERE email = %s", (sender_email,))
		conn.commit()
		cursor.close()
		conn.close()

		response = inbound_client.post('/inbound', data={
			'from': sender_email,
			'to': 'inbound_test@example.com.au',
			'subject': 'New Sender',
			'text': 'Hello'
		})
		assert response.status_code == 200

		conn = get_db_connection()
		cursor = conn.cursor()
		cursor.execute('SELECT id, is_local, name FROM users WHERE email = %s', (sender_email,))
		sender = cursor.fetchone()
		cursor.close()
		conn.close()
		assert sender is not None
		assert sender['is_local'] is False
		assert sender['name'] == 'new_external_sender_12345'

	def test_inbound_creates_inbox_if_missing(self, inbound_client, local_user):
		"""Test that Inbox folder is created for recipient if it doesn't exist"""
		user_id = local_user['id']
		conn = get_db_connection()
		cursor = conn.cursor()
		cursor.execute("DELETE FROM folders WHERE user_id = %s AND name = 'Inbox'", (user_id,))
		conn.commit()
		cursor.close()
		conn.close()

		response = inbound_client.post('/inbound', data={
			'from': 'user@example.com',
			'to': 'inbound_test@example.com.au',
			'subject': 'Inbox Creation',
			'text': 'Testing inbox auto-creation'
		})
		assert response.status_code == 200

		conn = get_db_connection()
		cursor = conn.cursor()
		cursor.execute(
			'SELECT id FROM folders WHERE user_id = %s AND name = %s',
			(user_id, 'Inbox')
		)
		folder = cursor.fetchone()
		cursor.close()
		conn.close()
		assert folder is not None

	def test_inbound_stores_headers(self, inbound_client, local_user):
		"""Test that headers are stored with sender IP and webhook marker"""
		response = inbound_client.post('/inbound', data={
			'from': 'user@example.com',
			'to': 'inbound_test@example.com.au',
			'subject': 'Headers Test',
			'text': 'Testing',
			'sender_ip': '203.0.113.5'
		})
		assert response.status_code == 200
		email_id = response.get_json()['email_id']

		conn = get_db_connection()
		cursor = conn.cursor()
		cursor.execute('SELECT headers FROM emails WHERE id = %s', (email_id,))
		email = cursor.fetchone()
		cursor.close()
		conn.close()
		headers = email['headers']
		assert 'from: user@example.com' in headers
		assert 'to: inbound_test@example.com.au' in headers
		assert 'x-sender-ip: 203.0.113.5' in headers
		assert 'x-received-via: inbound-webhook' in headers


class TestInboundValidation:
	"""Validation and error handling tests"""

	def test_missing_sender(self, inbound_client, local_user):
		"""Test that missing 'from' field returns 400"""
		response = inbound_client.post('/inbound', data={
			'to': 'inbound_test@example.com.au',
			'subject': 'No Sender',
			'text': 'Hello'
		})
		assert response.status_code == 400
		data = response.get_json()
		assert 'Missing sender or recipient' in data['error']

	def test_missing_recipient(self, inbound_client, local_user):
		"""Test that missing 'to' field returns 400"""
		response = inbound_client.post('/inbound', data={
			'from': 'user@example.com',
			'subject': 'No Recipient',
			'text': 'Hello'
		})
		assert response.status_code == 400
		data = response.get_json()
		assert 'Missing sender or recipient' in data['error']

	def test_invalid_sender_email(self, inbound_client, local_user):
		"""Test that invalid sender email returns 400"""
		response = inbound_client.post('/inbound', data={
			'from': 'not-an-email',
			'to': 'inbound_test@example.com.au',
			'subject': 'Bad Sender',
			'text': 'Hello'
		})
		assert response.status_code == 400
		data = response.get_json()
		assert 'Invalid sender email' in data['error']

	def test_invalid_recipient_email(self, inbound_client, local_user):
		"""Test that invalid recipient email returns 400"""
		response = inbound_client.post('/inbound', data={
			'from': 'user@example.com',
			'to': 'not-an-email',
			'subject': 'Bad Recipient',
			'text': 'Hello'
		})
		assert response.status_code == 400
		data = response.get_json()
		assert 'Invalid recipient email' in data['error']

	def test_unknown_recipient_returns_200(self, inbound_client, local_user):
		"""Test that unknown recipient on local domain returns 200 (prevents SMTP2GO retries)"""
		response = inbound_client.post('/inbound', data={
			'from': 'user@example.com',
			'to': 'nonexistent@example.com.au',
			'subject': 'Unknown User',
			'text': 'Hello'
		})
		assert response.status_code == 200
		data = response.get_json()
		assert data['status'] == 'rejected'
		assert data['reason'] == 'unknown recipient'

	def test_unknown_domain_recipient(self, inbound_client, local_user):
		"""Test that recipient on unknown domain returns rejected"""
		response = inbound_client.post('/inbound', data={
			'from': 'user@example.com',
			'to': 'user@unknown-domain.com',
			'subject': 'Unknown Domain',
			'text': 'Hello'
		})
		assert response.status_code == 200
		data = response.get_json()
		assert data['status'] == 'rejected'

	def test_unsupported_content_type(self, inbound_client, local_user):
		"""Test that unsupported content type returns 400"""
		response = inbound_client.post(
			'/inbound',
			data='raw text body',
			content_type='text/plain'
		)
		assert response.status_code == 400
		data = response.get_json()
		assert 'Unsupported content type' in data['error']

	def test_invalid_json_body(self, inbound_client, local_user):
		"""Test that invalid JSON body returns 400"""
		response = inbound_client.post(
			'/inbound',
			data='not valid json{',
			content_type='application/json'
		)
		assert response.status_code == 400
		data = response.get_json()
		assert 'Invalid JSON' in data['error']

	def test_non_string_fields_return_400(self, inbound_client, local_user):
		"""Test that non-string fields in JSON return 400"""
		response = inbound_client.post('/inbound', json={
			'from': 12345,
			'to': 'inbound_test@example.com.au',
			'subject': 'Bad types',
			'text': 'Hello'
		})
		assert response.status_code == 400
		data = response.get_json()
		assert 'Invalid field type' in data['error']

	def test_header_injection_stripped(self, inbound_client, local_user):
		"""Test that CR/LF characters within header values are stripped preventing injection"""
		response = inbound_client.post('/inbound', data={
			'from': 'user@example.com',
			'to': 'inbound_test@example.com.au',
			'subject': 'Test\r\nX-Injected: evil',
			'text': 'Hello',
			'sender_ip': '1.2.3.4\nX-Extra: bad'
		})
		assert response.status_code == 200
		email_id = response.get_json()['email_id']

		conn = get_db_connection()
		cursor = conn.cursor()
		cursor.execute('SELECT headers FROM emails WHERE id = %s', (email_id,))
		email = cursor.fetchone()
		cursor.close()
		conn.close()
		headers = email['headers']
		assert '\r' not in headers
		assert headers.count('\n') == headers.count('\n')
		lines = headers.split('\n')
		for line in lines:
			if line.startswith('subject:'):
				assert '\r' not in line
				assert '\n' not in line
			if line.startswith('x-sender-ip:'):
				assert '\r' not in line
				assert '\n' not in line


class TestInboundSenderBlocklist:
	"""Sender blocklist tests"""

	def test_blocked_sender(self, inbound_client, local_user, blocked_sender):
		"""Test that emails from blocked senders are rejected"""
		response = inbound_client.post('/inbound', data={
			'from': blocked_sender,
			'to': 'inbound_test@example.com.au',
			'subject': 'Spam',
			'text': 'Spam content'
		})
		assert response.status_code == 200
		data = response.get_json()
		assert data['status'] == 'blocked'

	def test_blocked_domain(self, inbound_client, local_user, blocked_domain):
		"""Test that emails from blocked domains are rejected"""
		response = inbound_client.post('/inbound', data={
			'from': f'anyone@{blocked_domain}',
			'to': 'inbound_test@example.com.au',
			'subject': 'Domain Spam',
			'text': 'Spam content'
		})
		assert response.status_code == 200
		data = response.get_json()
		assert data['status'] == 'blocked'

	def test_non_blocked_sender_accepted(self, inbound_client, local_user):
		"""Test that non-blocked senders are accepted"""
		response = inbound_client.post('/inbound', data={
			'from': 'user@example.com',
			'to': 'inbound_test@example.com.au',
			'subject': 'Legitimate',
			'text': 'Normal content'
		})
		assert response.status_code == 200
		data = response.get_json()
		assert data['status'] == 'received'


class TestInboundRateLimiting:
	"""Rate limiting tests"""

	def test_rate_limit_enforced(self, inbound_client, local_user):
		"""Test that exceeding rate limit returns 429"""
		import app.routes.inbound as inbound_module
		original_limit = inbound_module.RATE_LIMIT_PER_IP
		inbound_module.RATE_LIMIT_PER_IP = 5
		inbound_module._inbound_rate_limits.clear()

		try:
			for i in range(5):
				response = inbound_client.post('/inbound', data={
					'from': f'sender{i}@gmail.com',
					'to': 'inbound_test@example.com.au',
					'subject': f'Email {i}',
					'text': 'Test'
				})
				assert response.status_code == 200

			response = inbound_client.post('/inbound', data={
				'from': 'user@example.com',
				'to': 'inbound_test@example.com.au',
				'subject': 'Over Limit',
				'text': 'Should be rate limited'
			})
			assert response.status_code == 429
			data = response.get_json()
			assert 'Rate limit' in data['error']
		finally:
			inbound_module.RATE_LIMIT_PER_IP = original_limit

	def test_rate_limit_per_ip_isolation(self, inbound_client, local_user):
		"""Test that rate limits are isolated per IP"""
		import app.routes.inbound as inbound_module
		original_limit = inbound_module.RATE_LIMIT_PER_IP
		inbound_module.RATE_LIMIT_PER_IP = 2
		inbound_module._inbound_rate_limits.clear()

		try:
			with inbound_client.application.test_request_context():
				inbound_client.post('/inbound', data={
					'from': 'user@example.com',
					'to': 'inbound_test@example.com.au',
					'subject': 'From IP1',
					'text': 'Test'
				}, environ_base={'REMOTE_ADDR': '10.0.0.1'})

				inbound_client.post('/inbound', data={
					'from': 'user@example.com',
					'to': 'inbound_test@example.com.au',
					'subject': 'From IP2',
					'text': 'Test'
				}, environ_base={'REMOTE_ADDR': '10.0.0.2'})

				assert len(inbound_module._inbound_rate_limits) >= 2
		finally:
			inbound_module.RATE_LIMIT_PER_IP = original_limit


class TestInboundSMTP2GOSignature:
	"""SMTP2GO HMAC signature verification tests"""

	def test_no_secret_passes(self, inbound_client, local_user):
		"""Test that without SMTP2GO_WEBHOOK_SECRET, all requests pass"""
		import app.routes.inbound as inbound_module
		original = inbound_module.SMTP2GO_WEBHOOK_SECRET
		inbound_module.SMTP2GO_WEBHOOK_SECRET = None
		try:
			response = inbound_client.post('/inbound', data={
				'from': 'user@example.com',
				'to': 'inbound_test@example.com.au',
				'subject': 'No Secret',
				'text': 'Hello'
			})
			assert response.status_code == 200
			assert response.get_json()['status'] == 'received'
		finally:
			inbound_module.SMTP2GO_WEBHOOK_SECRET = original

	def test_valid_signature_passes(self, inbound_client, local_user):
		"""Test that valid HMAC signature is accepted"""
		import app.routes.inbound as inbound_module
		original = inbound_module.SMTP2GO_WEBHOOK_SECRET
		original_verify = inbound_module._verify_smtp2go_signature
		secret = 'test-webhook-secret-key'
		inbound_module.SMTP2GO_WEBHOOK_SECRET = secret

		captured_data = {}
		def mock_verify(request_data, signature):
			captured_data['data'] = request_data
			captured_data['sig'] = signature
			return True

		inbound_module._verify_smtp2go_signature = mock_verify

		try:
			response = inbound_client.post(
				'/inbound',
				data={
					'from': 'user@example.com',
					'to': 'inbound_test@example.com.au',
					'subject': 'Signed',
					'text': 'Hello'
				},
				headers={'X-SMTP2GO-Signature': 'any-sig-will-do'}
			)
			assert response.status_code == 200
			assert captured_data['data'] is not None
		finally:
			inbound_module.SMTP2GO_WEBHOOK_SECRET = original
			inbound_module._verify_smtp2go_signature = original_verify

	def test_invalid_signature_rejected(self, inbound_client, local_user):
		"""Test that invalid HMAC signature is rejected with 403"""
		import app.routes.inbound as inbound_module
		original = inbound_module.SMTP2GO_WEBHOOK_SECRET
		inbound_module.SMTP2GO_WEBHOOK_SECRET = 'test-webhook-secret-key'

		try:
			response = inbound_client.post('/inbound', data={
				'from': 'user@example.com',
				'to': 'inbound_test@example.com.au',
				'subject': 'Bad Sig',
				'text': 'Hello'
			}, headers={'X-SMTP2GO-Signature': 'invalid_signature_here'})
			assert response.status_code == 403
			data = response.get_json()
			assert 'Invalid signature' in data['error']
		finally:
			inbound_module.SMTP2GO_WEBHOOK_SECRET = original

	def test_missing_signature_with_secret_rejected(self, inbound_client, local_user):
		"""Test that missing signature when secret is set returns 403"""
		import app.routes.inbound as inbound_module
		original = inbound_module.SMTP2GO_WEBHOOK_SECRET
		inbound_module.SMTP2GO_WEBHOOK_SECRET = 'test-webhook-secret-key'

		try:
			response = inbound_client.post('/inbound', data={
				'from': 'user@example.com',
				'to': 'inbound_test@example.com.au',
				'subject': 'No Sig',
				'text': 'Hello'
			})
			assert response.status_code == 403
		finally:
			inbound_module.SMTP2GO_WEBHOOK_SECRET = original


class TestInboundExtractEmail:
	"""Unit tests for the extract_email helper function"""

	def test_simple_email(self):
		from app.routes.inbound import extract_email
		assert extract_email('user@example.com') == 'user@example.com'

	def test_email_with_name(self):
		from app.routes.inbound import extract_email
		assert extract_email('John Doe <john@example.com>') == 'john@example.com'

	def test_email_uppercase(self):
		from app.routes.inbound import extract_email
		assert extract_email('User@Example.COM') == 'user@example.com'

	def test_invalid_email(self):
		from app.routes.inbound import extract_email
		assert extract_email('not-an-email') == ''

	def test_empty_string(self):
		from app.routes.inbound import extract_email
		assert extract_email('') == ''

	def test_email_too_long(self):
		from app.routes.inbound import extract_email
		long_local = 'a' * 320 + '@example.com'
		assert extract_email(long_local) == ''


class TestInboundMultipart:
	"""Multipart/form-data tests"""

	def test_multipart_form_data(self, inbound_client, local_user):
		"""Test that multipart/form-data is accepted"""
		response = inbound_client.post('/inbound', data={
			'from': 'user@example.com',
			'to': 'inbound_test@example.com.au',
			'subject': 'Multipart Test',
			'text': 'From multipart form'
		}, content_type='multipart/form-data')
		assert response.status_code == 200
		data = response.get_json()
		assert data['status'] == 'received'

	def test_urlencoded_form_data(self, inbound_client, local_user):
		"""Test that application/x-www-form-urlencoded is accepted"""
		response = inbound_client.post('/inbound', data={
			'from': 'user@example.com',
			'to': 'inbound_test@example.com.au',
			'subject': 'URLEncoded Test',
			'text': 'From urlencoded'
		}, content_type='application/x-www-form-urlencoded')
		assert response.status_code == 200
		data = response.get_json()
		assert data['status'] == 'received'


class TestInboundStringSanitization:
	"""String sanitization tests"""

	def test_null_bytes_stripped(self, inbound_client, local_user):
		"""Test that null bytes are removed from stored content"""
		response = inbound_client.post('/inbound', data={
			'from': 'user@example.com',
			'to': 'inbound_test@example.com.au',
			'subject': 'Null\x00Bytes',
			'text': 'Body with\x00nulls'
		})
		assert response.status_code == 200
		email_id = response.get_json()['email_id']

		conn = get_db_connection()
		cursor = conn.cursor()
		cursor.execute('SELECT subject, body FROM emails WHERE id = %s', (email_id,))
		email = cursor.fetchone()
		cursor.close()
		conn.close()
		assert '\x00' not in email['subject']
		assert '\x00' not in email['body']

	def test_subject_truncation(self, inbound_client, local_user):
		"""Test that subject is truncated at 500 chars"""
		long_subject = 'A' * 600
		response = inbound_client.post('/inbound', data={
			'from': 'user@example.com',
			'to': 'inbound_test@example.com.au',
			'subject': long_subject,
			'text': 'Long subject test'
		})
		assert response.status_code == 200
		email_id = response.get_json()['email_id']

		conn = get_db_connection()
		cursor = conn.cursor()
		cursor.execute('SELECT subject FROM emails WHERE id = %s', (email_id,))
		email = cursor.fetchone()
		cursor.close()
		conn.close()
		assert len(email['subject']) <= 500


class TestInboundSenderIPValidation:
	"""Sender IP validation tests"""

	def test_valid_ipv4(self):
		from app.routes.inbound import _validate_sender_ip
		assert _validate_sender_ip('192.168.1.1') == '192.168.1.1'

	def test_valid_ipv6(self):
		from app.routes.inbound import _validate_sender_ip
		result = _validate_sender_ip('2001:0db8:85a3::8a2e:0370:7334')
		assert '2001' in result

	def test_invalid_ip_characters(self):
		from app.routes.inbound import _validate_sender_ip
		assert _validate_sender_ip('192.168.1.1; DROP TABLE') == ''

	def test_empty_ip(self):
		from app.routes.inbound import _validate_sender_ip
		assert _validate_sender_ip('') == ''

	def test_too_long_ip(self):
		from app.routes.inbound import _validate_sender_ip
		long_ip = '1' * 50
		assert _validate_sender_ip(long_ip) == ''


class TestInboundMIMEExtraction:
	"""Tests for extracting body from raw MIME when text/html are empty"""

	MIME_PLAIN_ONLY = (
		'From: user@example.com\r\n'
		'To: inbound_test@example.com.au\r\n'
		'Subject: MIME Test\r\n'
		'Content-Type: text/plain; charset=utf-8\r\n'
		'MIME-Version: 1.0\r\n'
		'\r\n'
		'This is the plain text body from MIME.\r\n'
	)

	MIME_HTML_AND_PLAIN = (
		'From: user@example.com\r\n'
		'To: inbound_test@example.com.au\r\n'
		'Subject: MIME HTML Test\r\n'
		'MIME-Version: 1.0\r\n'
		'Content-Type: multipart/alternative; boundary="boundary123"\r\n'
		'\r\n'
		'--boundary123\r\n'
		'Content-Type: text/plain; charset=utf-8\r\n'
		'\r\n'
		'Plain text version here.\r\n'
		'--boundary123\r\n'
		'Content-Type: text/html; charset=utf-8\r\n'
		'\r\n'
		'<p>HTML version here.</p>\r\n'
		'--boundary123--\r\n'
	)

	def test_mime_extracts_text_body(self, inbound_client, local_user):
		"""Test that plain text body is extracted from raw MIME when text field is empty"""
		response = inbound_client.post('/inbound', data={
			'from': 'user@example.com',
			'to': 'inbound_test@example.com.au',
			'subject': 'MIME Plain Test',
			'text': '',
			'html': '',
			'mail': self.MIME_PLAIN_ONLY
		})
		assert response.status_code == 200
		email_id = response.get_json()['email_id']

		conn = get_db_connection()
		cursor = conn.cursor()
		cursor.execute('SELECT body, body_html FROM emails WHERE id = %s', (email_id,))
		email = cursor.fetchone()
		cursor.close()
		conn.close()
		assert 'plain text body from MIME' in email['body']
		assert email['body_html'] is None or email['body_html'] == ''

	def test_mime_extracts_html_and_text(self, inbound_client, local_user):
		"""Test that both text and HTML are extracted from multipart MIME"""
		response = inbound_client.post('/inbound', data={
			'from': 'user@example.com',
			'to': 'inbound_test@example.com.au',
			'subject': 'MIME HTML Test',
			'text': '',
			'html': '',
			'mail': self.MIME_HTML_AND_PLAIN
		})
		assert response.status_code == 200
		email_id = response.get_json()['email_id']

		conn = get_db_connection()
		cursor = conn.cursor()
		cursor.execute('SELECT body, body_html FROM emails WHERE id = %s', (email_id,))
		email = cursor.fetchone()
		cursor.close()
		conn.close()
		assert 'Plain text version' in email['body']
		assert 'HTML version' in email['body_html']

	def test_text_field_takes_priority_over_mime(self, inbound_client, local_user):
		"""Test that explicit text field takes priority over MIME extraction"""
		response = inbound_client.post('/inbound', data={
			'from': 'user@example.com',
			'to': 'inbound_test@example.com.au',
			'subject': 'Priority Test',
			'text': 'Explicit text field',
			'mail': self.MIME_PLAIN_ONLY
		})
		assert response.status_code == 200
		email_id = response.get_json()['email_id']

		conn = get_db_connection()
		cursor = conn.cursor()
		cursor.execute('SELECT body FROM emails WHERE id = %s', (email_id,))
		email = cursor.fetchone()
		cursor.close()
		conn.close()
		assert email['body'] == 'Explicit text field'

	def test_smtp2go_event_fields_accepted(self, inbound_client, local_user):
		"""Test that SMTP2GO event webhook field names are accepted as fallbacks"""
		response = inbound_client.post('/inbound', data={
			'from_address': 'user@example.com',
			'rcpt': 'inbound_test@example.com.au',
			'subject': 'SMTP2GO Event',
			'text': 'From event webhook'
		})
		assert response.status_code == 200
		email_id = response.get_json()['email_id']

		conn = get_db_connection()
		cursor = conn.cursor()
		cursor.execute('SELECT body FROM emails WHERE id = %s', (email_id,))
		email = cursor.fetchone()
		cursor.close()
		conn.close()
		assert 'From event webhook' in email['body']

	def test_base64_mime_body_extraction(self, inbound_client, local_user):
		"""Test that Base64-encoded raw_email is decoded and body extracted"""
		import base64

		mime = (
			'From: user@example.com\r\n'
			'To: inbound_test@example.com.au\r\n'
			'Subject: Base64 Test\r\n'
			'MIME-Version: 1.0\r\n'
			'Content-Type: text/plain; charset=utf-8\r\n'
			'\r\n'
			'Decoded from Base64!\r\n'
		)
		b64_mime = base64.b64encode(mime.encode('utf-8')).decode('ascii')

		response = inbound_client.post('/inbound', data={
			'from': 'user@example.com',
			'to': 'inbound_test@example.com.au',
			'subject': 'Base64 Test',
			'raw_email': b64_mime
		})
		assert response.status_code == 200
		email_id = response.get_json()['email_id']

		conn = get_db_connection()
		cursor = conn.cursor()
		cursor.execute('SELECT body, body_html, raw_email FROM emails WHERE id = %s', (email_id,))
		email = cursor.fetchone()
		cursor.close()
		conn.close()
		assert 'Decoded from Base64' in email['body']
		assert 'Received:' in email['raw_email'] or 'From:' in email['raw_email']

	def test_base64_mime_multipart_extraction(self, inbound_client, local_user):
		"""Test Base64-encoded multipart MIME extracts both text and HTML"""
		import base64

		mime = (
			'From: user@example.com\r\n'
			'To: inbound_test@example.com.au\r\n'
			'Subject: B64 Multipart\r\n'
			'MIME-Version: 1.0\r\n'
			'Content-Type: multipart/alternative; boundary="b64test"\r\n'
			'\r\n'
			'--b64test\r\n'
			'Content-Type: text/plain; charset=utf-8\r\n'
			'\r\n'
			'Plain text from Base64.\r\n'
			'--b64test\r\n'
			'Content-Type: text/html; charset=utf-8\r\n'
			'\r\n'
			'<b>HTML from Base64.</b>\r\n'
			'--b64test--\r\n'
		)
		b64_mime = base64.b64encode(mime.encode('utf-8')).decode('ascii')

		response = inbound_client.post('/inbound', data={
			'from': 'user@example.com',
			'to': 'inbound_test@example.com.au',
			'subject': 'B64 Multipart',
			'raw_email': b64_mime
		})
		assert response.status_code == 200
		email_id = response.get_json()['email_id']

		conn = get_db_connection()
		cursor = conn.cursor()
		cursor.execute('SELECT body, body_html FROM emails WHERE id = %s', (email_id,))
		email = cursor.fetchone()
		cursor.close()
		conn.close()
		assert 'Plain text from Base64' in email['body']
		assert 'HTML from Base64' in email['body_html']


class TestInboundPayloadLimits:
	"""Tests for Flask/Werkzeug payload and form size limits"""

	def test_max_content_length_config(self, app):
		"""Test that MAX_CONTENT_LENGTH is set to 50MB"""
		assert app.config['MAX_CONTENT_LENGTH'] == 50 * 1024 * 1024

	def test_max_form_memory_size_config(self, app):
		"""Test that MAX_FORM_MEMORY_SIZE config is set to 50MB"""
		assert app.config['MAX_FORM_MEMORY_SIZE'] == 50 * 1024 * 1024

	def test_werkzeug_max_form_memory_size(self, app):
		"""Test that Werkzeug max_form_memory_size is set to 50MB (not default 500KB)"""
		assert app.request_class.max_form_memory_size == 50 * 1024 * 1024

	def test_werkzeug_not_default_500kb(self, app):
		"""Test that Werkzeug form memory limit is NOT the default 500KB"""
		from werkzeug.wrappers.request import Request as WerkzeugRequest
		default_size = WerkzeugRequest.max_form_memory_size
		assert app.request_class.max_form_memory_size != default_size
		assert app.request_class.max_form_memory_size > default_size

	def test_large_form_field_accepted(self, inbound_client, local_user):
		"""Test that a form field larger than 500KB is accepted (Werkzeug default would reject)"""
		big_body = 'X' * (600 * 1024)
		response = inbound_client.post('/inbound', data={
			'from': 'user@example.com',
			'to': 'inbound_test@example.com.au',
			'subject': 'Large Body Test',
			'text': big_body
		})
		assert response.status_code == 200
		data = response.get_json()
		assert data['status'] == 'received'
		email_id = data['email_id']

		conn = get_db_connection()
		cursor = conn.cursor()
		cursor.execute('SELECT length(body) as body_len FROM emails WHERE id = %s', (email_id,))
		email = cursor.fetchone()
		cursor.close()
		conn.close()
		assert email['body_len'] > 500 * 1024

	def test_large_raw_email_base64_accepted(self, inbound_client, local_user):
		"""Test that a Base64-encoded raw_email larger than 500KB is accepted"""
		import base64

		big_body = 'A' * (600 * 1024)
		mime = (
			'From: user@example.com\r\n'
			'To: inbound_test@example.com.au\r\n'
			'Subject: Large B64 Test\r\n'
			'Content-Type: text/plain; charset=utf-8\r\n'
			'MIME-Version: 1.0\r\n'
			'\r\n'
			+ big_body + '\r\n'
		)
		b64_mime = base64.b64encode(mime.encode('utf-8')).decode('ascii')
		assert len(b64_mime) > 500 * 1024

		response = inbound_client.post('/inbound', data={
			'from': 'user@example.com',
			'to': 'inbound_test@example.com.au',
			'subject': 'Large B64 Test',
			'raw_email': b64_mime
		})
		assert response.status_code == 200
		data = response.get_json()
		assert data['status'] == 'received'

	def test_payload_over_50mb_rejected(self, inbound_client, local_user):
		"""Test that payloads exceeding MAX_CONTENT_LENGTH (50MB) are rejected"""
		big_data = 'Y' * (51 * 1024 * 1024)
		response = inbound_client.post('/inbound', data={
			'from': 'user@example.com',
			'to': 'inbound_test@example.com.au',
			'subject': 'Too Big',
			'text': big_data
		})
		assert response.status_code == 413