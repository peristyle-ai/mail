"""Tests for CC support on POST /api/emails/mime."""

import pytest


class TestMimeCC:
	"""CC recipient behavior on the MIME send endpoint."""

	def test_mime_with_request_level_cc(self, client, auth_headers, db):
		"""Passing cc in the request body queues the CC recipient."""
		mime_content = (
			'Subject: MIME CC test\n'
			'From: test@example.com\n'
			'To: primary@external.com\n'
			'MIME-Version: 1.0\n'
			'Content-Type: text/plain; charset="utf-8"\n'
			'\n'
			'body\n'
		)

		response = client.post(
			'/api/emails/mime',
			headers=auth_headers,
			json={
				'to': 'primary@external.com',
				'cc': ['cc1@external.com', 'cc2@external.com'],
				'mime_content': mime_content,
			},
		)
		assert response.status_code == 201
		data = response.get_json()
		assert data['cc_count'] == 2

		conn = db()
		cursor = conn.cursor()
		cursor.execute(
			"SELECT recipient_email FROM outbound_queue WHERE email_id = %s ORDER BY recipient_email",
			(data['id'],),
		)
		queued = sorted(r['recipient_email'] for r in cursor.fetchall())
		cursor.close()
		conn.close()

		assert queued == ['cc1@external.com', 'cc2@external.com', 'primary@external.com']

	def test_mime_with_string_cc(self, client, auth_headers, db):
		"""A single CC string is accepted."""
		mime_content = (
			'Subject: MIME CC string\n'
			'From: test@example.com\n'
			'To: primary@external.com\n'
			'MIME-Version: 1.0\n'
			'Content-Type: text/plain; charset="utf-8"\n'
			'\n'
			'body\n'
		)

		response = client.post(
			'/api/emails/mime',
			headers=auth_headers,
			json={
				'to': 'primary@external.com',
				'cc': 'cc@external.com',
				'mime_content': mime_content,
			},
		)
		assert response.status_code == 201
		assert response.get_json()['cc_count'] == 1

	def test_mime_without_cc_returns_zero_count(self, client, auth_headers, db):
		"""Omitting cc returns cc_count=0."""
		mime_content = (
			'Subject: no cc\n'
			'From: test@example.com\n'
			'To: recipient@external.com\n'
			'MIME-Version: 1.0\n'
			'Content-Type: text/plain; charset="utf-8"\n'
			'\n'
			'body\n'
		)

		response = client.post(
			'/api/emails/mime',
			headers=auth_headers,
			json={
				'to': 'recipient@external.com',
				'mime_content': mime_content,
			},
		)
		assert response.status_code == 201
		assert response.get_json()['cc_count'] == 0

	def test_mime_falls_back_to_cc_header_in_message(self, client, auth_headers, db):
		"""If cc is not in the request body but the MIME has a Cc: header, use it."""
		mime_content = (
			'Subject: MIME Cc header\n'
			'From: test@example.com\n'
			'To: primary@external.com\n'
			'Cc: ccfriend@external.com\n'
			'MIME-Version: 1.0\n'
			'Content-Type: text/plain; charset="utf-8"\n'
			'\n'
			'body\n'
		)

		response = client.post(
			'/api/emails/mime',
			headers=auth_headers,
			json={
				'to': 'primary@external.com',
				'mime_content': mime_content,
			},
		)
		assert response.status_code == 201
		assert response.get_json()['cc_count'] == 1

		conn = db()
		cursor = conn.cursor()
		cursor.execute(
			"SELECT recipient_email FROM outbound_queue WHERE email_id = %s ORDER BY recipient_email",
			(response.get_json()['id'],),
		)
		queued = sorted(r['recipient_email'] for r in cursor.fetchall())
		cursor.close()
		conn.close()

		assert queued == ['ccfriend@external.com', 'primary@external.com']

	def test_mime_request_cc_overrides_message_cc(self, client, auth_headers, db):
		"""Request-level cc takes priority over a Cc: header in the MIME body."""
		mime_content = (
			'Subject: cc override\n'
			'From: test@example.com\n'
			'To: primary@external.com\n'
			'Cc: original@external.com\n'
			'MIME-Version: 1.0\n'
			'Content-Type: text/plain; charset="utf-8"\n'
			'\n'
			'body\n'
		)

		response = client.post(
			'/api/emails/mime',
			headers=auth_headers,
			json={
				'to': 'primary@external.com',
				'cc': 'override@external.com',
				'mime_content': mime_content,
			},
		)
		assert response.status_code == 201
		assert response.get_json()['cc_count'] == 1

		conn = db()
		cursor = conn.cursor()
		cursor.execute(
			"SELECT recipient_email FROM outbound_queue WHERE email_id = %s",
			(response.get_json()['id'],),
		)
		queued = [r['recipient_email'] for r in cursor.fetchall()]
		cursor.close()
		conn.close()

		# The request-level cc wins; original is not queued
		assert 'override@external.com' in queued
		assert 'original@external.com' not in queued

	def test_mime_cc_with_display_name_parsed_correctly(self, client, auth_headers, db):
		"""A Cc: header with display names ('Name <addr>') is parsed for the bare address."""
		mime_content = (
			'Subject: named cc\n'
			'From: test@example.com\n'
			'To: primary@external.com\n'
			'Cc: Friend <ccfriend@external.com>, Other <other@external.com>\n'
			'MIME-Version: 1.0\n'
			'Content-Type: text/plain; charset="utf-8"\n'
			'\n'
			'body\n'
		)

		response = client.post(
			'/api/emails/mime',
			headers=auth_headers,
			json={
				'to': 'primary@external.com',
				'mime_content': mime_content,
			},
		)
		assert response.status_code == 201
		assert response.get_json()['cc_count'] == 2

	def test_mime_cc_local_user_gets_inbox_copy(self, client, auth_headers, auth_headers_second_user, db):
		"""A local CC user in the MIME Cc: header receives an Inbox copy."""
		mime_content = (
			'Subject: cc local\n'
			'From: test@example.com\n'
			'To: external@recipient.com\n'
			'Cc: test2@example.com\n'
			'MIME-Version: 1.0\n'
			'Content-Type: text/plain; charset="utf-8"\n'
			'\n'
			'body\n'
		)

		response = client.post(
			'/api/emails/mime',
			headers=auth_headers,
			json={
				'to': 'external@recipient.com',
				'mime_content': mime_content,
			},
		)
		assert response.status_code == 201

		list_response = client.get(
			'/api/emails?folder=Inbox',
			headers=auth_headers_second_user,
		)
		assert list_response.status_code == 200
		emails = list_response.get_json()
		subjects = [e['subject'] for e in emails]
		assert 'cc local' in subjects