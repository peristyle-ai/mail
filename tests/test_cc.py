"""Tests for CC recipient support on POST /api/emails."""

import pytest


class TestCC:
	"""CC recipient behavior on outbound email send."""

	def test_send_with_single_cc_external(self, client, auth_headers, db):
		"""A single CC string for an external address returns cc_count=1."""
		response = client.post(
			'/api/emails',
			headers=auth_headers,
			json={
				'to': 'recipient@example.com',
				'cc': 'cc@example.com',
				'subject': 'CC test',
				'body': 'CC body',
			},
		)
		assert response.status_code == 201
		data = response.get_json()
		assert 'id' in data
		assert data['cc_count'] == 1

	def test_send_with_cc_array(self, client, auth_headers, db):
		"""CC as an array of strings is accepted and counted."""
		response = client.post(
			'/api/emails',
			headers=auth_headers,
			json={
				'to': 'recipient@example.com',
				'cc': ['cc1@example.com', 'cc2@example.com'],
				'subject': 'CC array',
				'body': 'CC body',
			},
		)
		assert response.status_code == 201
		assert response.get_json()['cc_count'] == 2

	def test_send_without_cc_returns_zero_count(self, client, auth_headers, db):
		"""When cc is omitted the response includes cc_count=0."""
		response = client.post(
			'/api/emails',
			headers=auth_headers,
			json={
				'to': 'recipient@example.com',
				'subject': 'No cc',
				'body': 'body',
			},
		)
		assert response.status_code == 201
		assert response.get_json()['cc_count'] == 0

	def test_cc_external_queued_for_delivery(self, client, auth_headers, db):
		"""External CC addresses appear in outbound_queue."""
		conn = db()
		cursor = conn.cursor()
		try:
			cursor.execute("DELETE FROM outbound_queue WHERE recipient_email IN ('cc1@external.com', 'cc2@external.com')")
			conn.commit()
		finally:
			cursor.close()
			conn.close()

		response = client.post(
			'/api/emails',
			headers=auth_headers,
			json={
				'to': 'primary@external.com',
				'cc': ['cc1@external.com', 'cc2@external.com'],
				'subject': 'CC queue',
				'body': 'body',
			},
		)
		assert response.status_code == 201
		email_id = response.get_json()['id']

		conn = db()
		cursor = conn.cursor()
		try:
			cursor.execute(
				"SELECT recipient_email FROM outbound_queue WHERE email_id = %s ORDER BY recipient_email",
				(email_id,),
			)
			queued = [r['recipient_email'] for r in cursor.fetchall()]
		finally:
			cursor.close()
			conn.close()

		assert queued == ['cc1@external.com', 'cc2@external.com', 'primary@external.com']

	def test_cc_local_user_gets_inbox_copy(self, client, auth_headers, auth_headers_second_user, db):
		"""A local CC user receives an Inbox copy."""
		response = client.post(
			'/api/emails',
			headers=auth_headers,
			json={
				'to': 'external@recipient.com',
				'cc': ['test2@example.com'],
				'subject': 'CC local',
				'body': 'body',
			},
		)
		assert response.status_code == 201

		# Second user should see this in their inbox
		list_response = client.get(
			'/api/emails?folder=Inbox',
			headers=auth_headers_second_user,
		)
		assert list_response.status_code == 200
		emails = list_response.get_json()
		subjects = [e['subject'] for e in emails]
		assert 'CC local' in subjects

	def test_cc_local_recorded_as_cc_type(self, client, auth_headers, auth_headers_second_user, db):
		"""The local CC copy is recorded as recipient_type='cc'."""
		response = client.post(
			'/api/emails',
			headers=auth_headers,
			json={
				'to': 'external@recipient.com',
				'cc': ['test2@example.com'],
				'subject': 'CC type',
				'body': 'body',
			},
		)
		assert response.status_code == 201

		conn = db()
		cursor = conn.cursor()
		try:
			cursor.execute(
				"""SELECT er.recipient_type
				   FROM email_recipients er
				   JOIN users u ON er.user_id = u.id
				   WHERE u.email = 'test2@example.com'
				   ORDER BY er.id DESC LIMIT 1"""
			)
			row = cursor.fetchone()
		finally:
			cursor.close()
			conn.close()

		assert row is not None
		assert row['recipient_type'] == 'cc'

	def test_to_takes_priority_over_cc_for_duplicate(self, client, auth_headers, db):
		"""If an address appears in both to and cc, it's stored as 'to'."""
		response = client.post(
			'/api/emails',
			headers=auth_headers,
			json={
				'to': 'shared@recipient.com',
				'cc': ['shared@recipient.com'],
				'subject': 'Dedup',
				'body': 'body',
			},
		)
		assert response.status_code == 201

		conn = db()
		cursor = conn.cursor()
		try:
			cursor.execute(
				"""SELECT er.recipient_type, COUNT(*) as cnt
				   FROM email_recipients er
				   JOIN emails e ON er.email_id = e.id
				   WHERE e.subject = 'Dedup'
				   GROUP BY er.recipient_type"""
			)
			rows = cursor.fetchall()
		finally:
			cursor.close()
			conn.close()

		# Only one entry, of type 'to'
		assert len(rows) == 1
		assert rows[0]['recipient_type'] == 'to'

	def test_cc_empty_string_rejected(self, client, auth_headers, db):
		"""An empty CC entry returns 400."""
		response = client.post(
			'/api/emails',
			headers=auth_headers,
			json={
				'to': 'recipient@example.com',
				'cc': [''],
				'subject': 'Empty CC',
				'body': 'body',
			},
		)
		assert response.status_code == 400

	def test_cc_non_string_entry_rejected(self, client, auth_headers, db):
		"""A non-string CC entry returns 400."""
		response = client.post(
			'/api/emails',
			headers=auth_headers,
			json={
				'to': 'recipient@example.com',
				'cc': [123],
				'subject': 'Bad CC',
				'body': 'body',
			},
		)
		assert response.status_code == 400

	def test_cc_non_list_non_string_rejected(self, client, auth_headers, db):
		"""A non-list, non-string CC returns 400."""
		response = client.post(
			'/api/emails',
			headers=auth_headers,
			json={
				'to': 'recipient@example.com',
				'cc': {'address': 'cc@example.com'},
				'subject': 'Bad CC',
				'body': 'body',
			},
		)
		assert response.status_code == 400


class TestCCDeliveryPreservesHeaders:
	"""Verify that delivery preserves the full To/Cc headers (RFC 5322)."""

	def test_delivery_to_cc_recipient_keeps_original_to_header(self, client, auth_headers, db, monkeypatch):
		"""When delivering to a CC recipient, To: must still show the full list."""
		from smtp_server.outbound.queue_processor import OutboundQueueProcessor

		# Send with one To + one CC (both external)
		response = client.post(
			'/api/emails',
			headers=auth_headers,
			json={
				'to': 'primary@external.com',
				'cc': 'ccfriend@external.com',
				'subject': 'Header preservation',
				'body': 'body',
			},
		)
		assert response.status_code == 201
		email_id = response.get_json()['id']

		conn = db()
		cursor = conn.cursor()
		cursor.execute(
			'''INSERT INTO domains (domain, relay_provider, relay_host, relay_port,
			   relay_username, relay_password_encrypted, relay_verified)
			   VALUES (%s, %s, %s, %s, %s, %s, %s)''',
			('example.com', 'smtp2go', 'mail-au.smtp2go.com', 2525, 'example.com', 'pw', True)
		)
		# Find the CC queue entry (recipient = ccfriend@external.com)
		cursor.execute(
			'''SELECT id, recipient_email, recipient_domain, attempt_count
			   FROM outbound_queue WHERE email_id = %s AND recipient_email = %s''',
			(email_id, 'ccfriend@external.com'),
		)
		queue_entry = cursor.fetchone()
		conn.commit()
		cursor.close()
		conn.close()

		delivered = {}

		def fake_deliver(self, from_address, to_addresses, message):
			delivered['to_header'] = message.get('To')
			delivered['cc_header'] = message.get('Cc')
			delivered['envelope_to'] = to_addresses[0]
			return True, 'ok'

		monkeypatch.setattr(
			'smtp_server.outbound.queue_processor.SMTP2GODelivery.deliver',
			fake_deliver,
		)

		processor = OutboundQueueProcessor(check_interval=30, max_retries=1)
		processor.dkim_signer = None
		processor.dkim_signers = {}
		processor.mx_lookup.get_mail_server = lambda r: (_ for _ in ()).throw(AssertionError('MX lookup should not run'))

		processor._process_email(
			queue_entry['id'],
			email_id,
			queue_entry['recipient_email'],
			queue_entry['recipient_domain'],
			queue_entry['attempt_count'],
		)

		# Envelope RCPT TO is the CC recipient (just them)
		assert delivered['envelope_to'] == 'ccfriend@external.com'

		# But the MIME To: header still shows the original primary recipient,
		# not the CC recipient. Cc: shows the CC list.
		assert delivered['to_header'] == 'primary@external.com'
		assert delivered['cc_header'] == 'ccfriend@external.com'

	def test_delivery_to_to_recipient_preserves_cc_header(self, client, auth_headers, db, monkeypatch):
		"""When delivering to a To recipient, Cc: must show the CC list, not be empty."""
		from smtp_server.outbound.queue_processor import OutboundQueueProcessor

		response = client.post(
			'/api/emails',
			headers=auth_headers,
			json={
				'to': 'primary@external.com',
				'cc': 'ccfriend@external.com',
				'subject': 'Header preservation to',
				'body': 'body',
			},
		)
		assert response.status_code == 201
		email_id = response.get_json()['id']

		conn = db()
		cursor = conn.cursor()
		cursor.execute(
			'''INSERT INTO domains (domain, relay_provider, relay_host, relay_port,
			   relay_username, relay_password_encrypted, relay_verified)
			   VALUES (%s, %s, %s, %s, %s, %s, %s)''',
			('example.com', 'smtp2go', 'mail-au.smtp2go.com', 2525, 'example.com', 'pw', True)
		)
		cursor.execute(
			'''SELECT id, recipient_email, recipient_domain, attempt_count
			   FROM outbound_queue WHERE email_id = %s AND recipient_email = %s''',
			(email_id, 'primary@external.com'),
		)
		queue_entry = cursor.fetchone()
		conn.commit()
		cursor.close()
		conn.close()

		delivered = {}

		def fake_deliver(self, from_address, to_addresses, message):
			delivered['to_header'] = message.get('To')
			delivered['cc_header'] = message.get('Cc')
			return True, 'ok'

		monkeypatch.setattr(
			'smtp_server.outbound.queue_processor.SMTP2GODelivery.deliver',
			fake_deliver,
		)

		processor = OutboundQueueProcessor(check_interval=30, max_retries=1)
		processor.dkim_signer = None
		processor.dkim_signers = {}
		processor.mx_lookup.get_mail_server = lambda r: (_ for _ in ()).throw(AssertionError('MX lookup should not run'))

		processor._process_email(
			queue_entry['id'],
			email_id,
			queue_entry['recipient_email'],
			queue_entry['recipient_domain'],
			queue_entry['attempt_count'],
		)

		assert delivered['to_header'] == 'primary@external.com'
		assert delivered['cc_header'] == 'ccfriend@external.com'