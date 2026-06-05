from smtp_server.outbound.queue_processor import OutboundQueueProcessor


class TestOutboundRelay:
	"""Tests for relay-backed outbound delivery."""

	def test_queue_processor_uses_verified_domain_relay(self, client, auth_headers, db, monkeypatch):
		response = client.post('/api/emails', headers=auth_headers, json={
			'to': 'user@example.com',
			'subject': 'Relay path test',
			'body': 'This should use the configured relay'
		})

		assert response.status_code == 201
		email_id = response.get_json()['id']

		conn = db()
		cursor = conn.cursor()
		cursor.execute(
			'''INSERT INTO domains (
			   domain, relay_provider, relay_host, relay_port,
			   relay_username, relay_password_encrypted, relay_verified)
			   VALUES (%s, %s, %s, %s, %s, %s, %s)''',
			('example.com', 'smtp2go', 'mail-au.smtp2go.com', 2525, 'example.com', 'secret-password', True)
		)
		cursor.execute(
			'''SELECT id, recipient_email, recipient_domain, attempt_count
			   FROM outbound_queue WHERE email_id = %s''',
			(email_id,)
		)
		queue_entry = cursor.fetchone()
		conn.commit()
		cursor.close()
		conn.close()

		deliveries = []

		def fake_deliver(self, from_address, to_addresses, message):
			deliveries.append({
				'from_address': from_address,
				'to_addresses': to_addresses,
				'subject': message['Subject'],
			})
			return True, 'Delivered via relay'

		monkeypatch.setattr(
			'smtp_server.outbound.queue_processor.SMTP2GODelivery.deliver',
			fake_deliver
		)

		processor = OutboundQueueProcessor(check_interval=30, max_retries=1)
		processor.dkim_signer = None
		processor.dkim_signers = {}
		processor.mx_lookup.get_mail_server = lambda recipient: (_ for _ in ()).throw(AssertionError('MX lookup should not run'))

		processor._process_email(
			queue_entry['id'],
			email_id,
			queue_entry['recipient_email'],
			queue_entry['recipient_domain'],
			queue_entry['attempt_count']
		)

		assert len(deliveries) == 1
		assert deliveries[0]['from_address'] == 'test@example.com'
		assert deliveries[0]['to_addresses'] == ['user@example.com']

		conn = db()
		cursor = conn.cursor()
		cursor.execute('SELECT status FROM outbound_queue WHERE id = %s', (queue_entry['id'],))
		status_row = cursor.fetchone()
		cursor.execute(
			'''SELECT remote_server FROM delivery_logs
			   WHERE outbound_queue_id = %s AND event_type = 'success'
			   ORDER BY id DESC LIMIT 1''',
			(queue_entry['id'],)
		)
		log_row = cursor.fetchone()
		cursor.close()
		conn.close()

		assert status_row['status'] == 'sent'
		assert log_row['remote_server'] == 'mail-au.smtp2go.com:2525'

	def test_queue_processor_preserves_mime_attachment_from_raw_email(self, client, auth_headers, db, monkeypatch):
		mime_content = (
			'Subject: MIME relay attachment test\n'
			'From: test@example.com\n'
			'To: user@example.com\n'
			'MIME-Version: 1.0\n'
			'Content-Type: multipart/mixed; boundary="==mime=="\n'
			'\n'
			'--==mime==\n'
			'Content-Type: text/plain; charset="utf-8"\n'
			'\n'
			'Hello with attachment\n'
			'--==mime==\n'
			'Content-Type: application/pdf\n'
			'Content-Transfer-Encoding: base64\n'
			'Content-Disposition: attachment; filename="invoice.pdf"\n'
			'\n'
			'JVBERi0xLjQK\n'
			'--==mime==--\n'
		)

		conn = db()
		cursor = conn.cursor()
		cursor.execute("SELECT id FROM users WHERE email = 'test@example.com'")
		user = cursor.fetchone()
		cursor.execute(
			'''INSERT INTO folders (user_id, name)
			   VALUES (%s, %s)
			   ON CONFLICT (user_id, name) DO UPDATE SET name = EXCLUDED.name
			   RETURNING id''',
			(user['id'], 'Sent')
		)
		sent_folder = cursor.fetchone()
		cursor.execute(
			'''INSERT INTO emails (
			   sender_id, folder_id, subject, body, raw_email, headers, is_read
			   ) VALUES (%s, %s, %s, %s, %s, %s, %s)
			   RETURNING id''',
			(user['id'], sent_folder['id'], 'MIME relay attachment test', mime_content, mime_content, '', True)
		)
		email_id = cursor.fetchone()['id']
		cursor.execute(
			'''INSERT INTO outbound_queue (
			   email_id, recipient_email, recipient_domain, status
			   ) VALUES (%s, %s, %s, %s)
			   RETURNING id, recipient_email, recipient_domain, attempt_count''',
			(email_id, 'user@example.com', 'gmail.com', 'pending')
		)
		queue_entry = cursor.fetchone()
		cursor.execute(
			'''INSERT INTO domains (
			   domain, relay_provider, relay_host, relay_port,
			   relay_username, relay_password_encrypted, relay_verified)
			   VALUES (%s, %s, %s, %s, %s, %s, %s)''',
			('example.com', 'smtp2go', 'mail-au.smtp2go.com', 2525, 'example.com', 'secret-password', True)
		)
		conn.commit()
		cursor.close()
		conn.close()

		deliveries = []

		def fake_deliver(self, from_address, to_addresses, message):
			attachments = []
			for part in message.iter_attachments():
				attachments.append(part.get_filename())
			deliveries.append({
				'is_multipart': message.is_multipart(),
				'attachments': attachments,
				'body': message.get_body(preferencelist=('plain',)).get_content(),
			})
			return True, 'Delivered via relay'

		monkeypatch.setattr(
			'smtp_server.outbound.queue_processor.SMTP2GODelivery.deliver',
			fake_deliver
		)

		processor = OutboundQueueProcessor(check_interval=30, max_retries=1)
		processor.dkim_signer = None
		processor.dkim_signers = {}
		processor.mx_lookup.get_mail_server = lambda recipient: (_ for _ in ()).throw(AssertionError('MX lookup should not run'))

		processor._process_email(
			queue_entry['id'],
			email_id,
			queue_entry['recipient_email'],
			queue_entry['recipient_domain'],
			queue_entry['attempt_count']
		)

		assert len(deliveries) == 1
		assert deliveries[0]['is_multipart'] is True
		assert deliveries[0]['attachments'] == ['invoice.pdf']
		assert 'Hello with attachment' in deliveries[0]['body']
