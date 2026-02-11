import pytest


class TestAuth:
	"""Authentication tests including security tests"""
	
	def test_register_success(self, client, db):
		"""Test successful user registration"""
		response = client.post('/auth/register', json={
			'email': 'newuser@example.com',
			'password': 'securepassword123',
			'name': 'New User'
		})
		assert response.status_code == 201
		data = response.get_json()
		assert 'id' in data
		assert data['email'] == 'newuser@example.com'
	
	def test_register_duplicate_email(self, client, db):
		"""Test registration with duplicate email returns 409"""
		client.post('/auth/register', json={
			'email': 'duplicate@example.com',
			'password': 'password123',
			'name': 'User 1'
		})
		
		response = client.post('/auth/register', json={
			'email': 'duplicate@example.com',
			'password': 'differentpassword',
			'name': 'User 2'
		})
		assert response.status_code == 409
		assert 'error' in response.get_json()
	
	def test_register_missing_email(self, client, db):
		"""Test registration without email returns 400"""
		response = client.post('/auth/register', json={
			'password': 'password123',
			'name': 'Test User'
		})
		assert response.status_code == 400
	
	def test_register_missing_password(self, client, db):
		"""Test registration without password returns 400"""
		response = client.post('/auth/register', json={
			'email': 'test@example.com',
			'name': 'Test User'
		})
		assert response.status_code == 400
	
	def test_login_success(self, client, db):
		"""Test successful login with valid credentials"""
		client.post('/auth/register', json={
			'email': 'loginuser@example.com',
			'password': 'testpassword123',
			'name': 'Login User'
		})
		
		response = client.post('/auth/login', json={
			'email': 'loginuser@example.com',
			'password': 'testpassword123'
		})
		assert response.status_code == 200
		data = response.get_json()
		assert 'token' in data
		assert 'user' in data
		assert data['user']['email'] == 'loginuser@example.com'
	
	def test_login_invalid_password(self, client, db):
		"""Test login with wrong password returns 401"""
		client.post('/auth/register', json={
			'email': 'wrongpass@example.com',
			'password': 'correctpassword',
			'name': 'Wrong Pass User'
		})
		
		response = client.post('/auth/login', json={
			'email': 'wrongpass@example.com',
			'password': 'wrongpassword'
		})
		assert response.status_code == 401
		assert 'error' in response.get_json()
	
	def test_login_nonexistent_user(self, client, db):
		"""Test login with non-existent user returns 401"""
		response = client.post('/auth/login', json={
			'email': 'nonexistent@example.com',
			'password': 'somepassword'
		})
		assert response.status_code == 401
		assert 'error' in response.get_json()
	
	def test_protected_endpoint_without_token(self, client, db):
		"""Test accessing protected endpoint without token returns 401"""
		response = client.get('/api/emails')
		assert response.status_code == 401
	
	def test_protected_endpoint_with_invalid_token(self, client, db):
		"""Test accessing protected endpoint with invalid token returns 401"""
		response = client.get('/api/emails', headers={
			'Authorization': 'Bearer invalid_token_here'
		})
		assert response.status_code == 401
	
	def test_sql_injection_in_email(self, client, db):
		"""Test SQL injection attempts are prevented"""
		response = client.post('/auth/register', json={
			'email': "test@example.com'; DROP TABLE users; --",
			'password': 'password123',
			'name': 'SQL Injection Test'
		})
		# Should either succeed with escaped email or fail gracefully, not crash
		assert response.status_code in [201, 400, 409]
	
	def test_xss_in_name_field(self, client, db):
		"""Test XSS attempts in name field are handled"""
		response = client.post('/auth/register', json={
			'email': 'xss@example.com',
			'password': 'password123',
			'name': '<script>alert("xss")</script>'
		})
		assert response.status_code == 201
		# The name should be stored (XSS prevention is UI concern)
		data = response.get_json()
		assert 'id' in data
	
	def test_very_long_password(self, client, db):
		"""Test password hashing handles very long passwords"""
		long_password = 'a' * 10000
		response = client.post('/auth/register', json={
			'email': 'longpass@example.com',
			'password': long_password,
			'name': 'Long Pass User'
		})
		assert response.status_code == 201
		
		# Verify can login with long password
		response = client.post('/auth/login', json={
			'email': 'longpass@example.com',
			'password': long_password
		})
		assert response.status_code == 200
