import uuid

import app.routes.auth as auth_module


def reset_login_state():
	auth_module._failed_login_attempts.clear()
	auth_module._login_lockouts.clear()


class TestAuth:
	"""Authentication tests including brute-force protection."""

	def test_register_success(self, client, db):
		reset_login_state()
		unique_email = f'newuser_{uuid.uuid4().hex[:8]}@example.com'
		response = client.post('/auth/register', json={
			'email': unique_email,
			'password': 'securepassword123',
			'name': 'New User'
		})
		assert response.status_code == 201
		data = response.get_json()
		assert 'id' in data
		assert data['email'] == unique_email

	def test_register_duplicate_email(self, client, db):
		reset_login_state()
		unique_email = f'duplicate_{uuid.uuid4().hex[:8]}@example.com'
		client.post('/auth/register', json={
			'email': unique_email,
			'password': 'password123',
			'name': 'User 1'
		})

		response = client.post('/auth/register', json={
			'email': unique_email,
			'password': 'differentpassword',
			'name': 'User 2'
		})
		assert response.status_code == 409
		assert 'error' in response.get_json()

	def test_register_missing_email(self, client, db):
		reset_login_state()
		response = client.post('/auth/register', json={
			'password': 'password123',
			'name': 'Test User'
		})
		assert response.status_code == 400

	def test_register_missing_password(self, client, db):
		reset_login_state()
		unique_email = f'missingpass_{uuid.uuid4().hex[:8]}@example.com'
		response = client.post('/auth/register', json={
			'email': unique_email,
			'name': 'Test User'
		})
		assert response.status_code == 400

	def test_login_success(self, client, db):
		reset_login_state()
		unique_email = f'loginuser_{uuid.uuid4().hex[:8]}@example.com'
		client.post('/auth/register', json={
			'email': unique_email,
			'password': 'testpassword123',
			'name': 'Login User'
		})

		response = client.post('/auth/login', json={
			'email': unique_email,
			'password': 'testpassword123'
		})
		assert response.status_code == 200
		data = response.get_json()
		assert 'token' in data
		assert 'user' in data
		assert data['user']['email'] == unique_email

	def test_login_invalid_password(self, client, db):
		reset_login_state()
		unique_email = f'wrongpass_{uuid.uuid4().hex[:8]}@example.com'
		client.post('/auth/register', json={
			'email': unique_email,
			'password': 'correctpassword',
			'name': 'Wrong Pass User'
		})

		response = client.post('/auth/login', json={
			'email': unique_email,
			'password': 'wrongpassword'
		})
		assert response.status_code == 401
		assert 'error' in response.get_json()

	def test_login_nonexistent_user(self, client, db):
		reset_login_state()
		response = client.post('/auth/login', json={
			'email': 'nonexistent@example.com',
			'password': 'somepassword'
		})
		assert response.status_code == 401
		assert 'error' in response.get_json()

	def test_protected_endpoint_without_token(self, client, db):
		reset_login_state()
		response = client.get('/api/emails')
		assert response.status_code == 401

	def test_protected_endpoint_with_invalid_token(self, client, db):
		reset_login_state()
		response = client.get('/api/emails', headers={
			'Authorization': 'Bearer invalid_token_here'
		})
		assert response.status_code == 401

	def test_sql_injection_in_email(self, client, db):
		reset_login_state()
		unique_email = f"sqlinject_{uuid.uuid4().hex[:8]}@example.com'; DROP TABLE users; --"
		response = client.post('/auth/register', json={
			'email': unique_email,
			'password': 'password123',
			'name': 'SQL Injection Test'
		})
		assert response.status_code in [201, 400, 409]

	def test_xss_in_name_field(self, client, db):
		reset_login_state()
		unique_email = f'xss_{uuid.uuid4().hex[:8]}@example.com'
		response = client.post('/auth/register', json={
			'email': unique_email,
			'password': 'password123',
			'name': '<script>alert("xss")</script>'
		})
		assert response.status_code == 201
		data = response.get_json()
		assert 'id' in data

	def test_very_long_password(self, client, db):
		reset_login_state()
		unique_email = f'longpass_{uuid.uuid4().hex[:8]}@example.com'
		long_password = 'a' * 10000
		response = client.post('/auth/register', json={
			'email': unique_email,
			'password': long_password,
			'name': 'Long Pass User'
		})
		assert response.status_code == 201

		response = client.post('/auth/login', json={
			'email': unique_email,
			'password': long_password
		})
		assert response.status_code == 200

	def test_login_brute_force_lockout(self, client, db):
		reset_login_state()
		client.post('/auth/register', json={
			'email': 'lockout_test@example.com',
			'password': 'correct-password',
			'name': 'Lockout Test',
		})

		for _ in range(auth_module.FAILED_LOGIN_LIMIT_PER_IP_EMAIL):
			response = client.post('/auth/login', json={
				'email': 'lockout_test@example.com',
				'password': 'wrong-password',
			}, environ_base={'REMOTE_ADDR': '203.0.113.10'})
			assert response.status_code == 401

		locked_response = client.post('/auth/login', json={
			'email': 'lockout_test@example.com',
			'password': 'correct-password',
		}, environ_base={'REMOTE_ADDR': '203.0.113.10'})
		assert locked_response.status_code == 429

	def test_successful_login_clears_failed_attempts(self, client, db):
		reset_login_state()
		client.post('/auth/register', json={
			'email': 'reset_test@example.com',
			'password': 'correct-password',
			'name': 'Reset Test',
		})

		for _ in range(auth_module.FAILED_LOGIN_LIMIT_PER_IP_EMAIL - 1):
			response = client.post('/auth/login', json={
				'email': 'reset_test@example.com',
				'password': 'wrong-password',
			}, environ_base={'REMOTE_ADDR': '203.0.113.11'})
			assert response.status_code == 401

		success_response = client.post('/auth/login', json={
			'email': 'reset_test@example.com',
			'password': 'correct-password',
		}, environ_base={'REMOTE_ADDR': '203.0.113.11'})
		assert success_response.status_code == 200

		follow_up_response = client.post('/auth/login', json={
			'email': 'reset_test@example.com',
			'password': 'wrong-password',
		}, environ_base={'REMOTE_ADDR': '203.0.113.11'})
		assert follow_up_response.status_code == 401
