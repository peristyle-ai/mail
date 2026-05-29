class TestDomains:
	"""Tests for per-domain relay configuration routes."""

	def test_list_domains_empty(self, client, auth_headers, db):
		response = client.get('/api/domains', headers=auth_headers)

		assert response.status_code == 200
		assert response.get_json() == {'domains': []}

	def test_set_and_get_domain_relay(self, client, auth_headers, db):
		response = client.put(
			'/api/domains/example.com/relay',
			headers=auth_headers,
			json={
				'relay_provider': 'smtp2go',
				'relay_username': 'example.com',
				'relay_password': 'secret-password',
				'relay_from_address': 'support@example.com',
			}
		)

		assert response.status_code == 200
		data = response.get_json()
		assert data['domain'] == 'example.com'
		assert data['relay_provider'] == 'smtp2go'
		assert data['relay_host'] == 'mail-au.smtp2go.com'
		assert data['relay_port'] == 2525
		assert data['relay_username'] == 'example.com'
		assert data['relay_from_address'] == 'support@example.com'
		assert data['relay_verified'] is False
		assert data['has_password'] is True

		get_response = client.get('/api/domains/example.com', headers=auth_headers)
		assert get_response.status_code == 200
		get_data = get_response.get_json()
		assert get_data['domain'] == 'example.com'
		assert get_data['relay_provider'] == 'smtp2go'
		assert get_data['has_password'] is True
		assert 'relay_password_encrypted' not in get_data

	def test_verify_domain_relay_marks_domain_verified(self, client, auth_headers, db, monkeypatch):
		client.put(
			'/api/domains/example.com/relay',
			headers=auth_headers,
			json={
				'relay_provider': 'smtp2go',
				'relay_username': 'example.com',
				'relay_password': 'secret-password',
			}
		)

		monkeypatch.setattr(
			'app.routes.domains.SMTP2GODelivery.verify_connection',
			lambda self: (True, 'Relay credentials verified successfully')
		)

		response = client.post('/api/domains/example.com/relay/verify', headers=auth_headers)

		assert response.status_code == 200
		data = response.get_json()
		assert data['success'] is True
		assert data['domain']['relay_verified'] is True
		assert data['domain']['relay_verified_at'] is not None

	def test_delete_domain_relay(self, client, auth_headers, db):
		client.put(
			'/api/domains/example.com/relay',
			headers=auth_headers,
			json={
				'relay_provider': 'smtp2go',
				'relay_username': 'example.com',
				'relay_password': 'secret-password',
			}
		)

		response = client.delete('/api/domains/example.com/relay', headers=auth_headers)

		assert response.status_code == 200
		data = response.get_json()
		assert data['success'] is True
		assert data['domain']['relay_provider'] is None
		assert data['domain']['has_password'] is False
		assert data['domain']['relay_verified'] is False
