import pytest
import uuid


class TestLegacyAuth:
	"""Auth tests using pytest fixtures"""
	
	def test_register_user(self, client, db):
		"""Test user registration with unique email"""
		unique_email = f'legacy_test_{uuid.uuid4().hex[:8]}@example.com'
		response = client.post('/auth/register', json={
			'email': unique_email,
			'password': 'test123',
			'name': 'Test User'
		})
		assert response.status_code == 201
		data = response.get_json()
		assert 'id' in data
		assert 'email' in data
		assert data['email'] == unique_email

	def test_login_user(self, client, db):
		"""Test user login with unique email"""
		unique_email = f'legacy_login_{uuid.uuid4().hex[:8]}@example.com'
		client.post('/auth/register', json={
			'email': unique_email,
			'password': 'test123',
			'name': 'Test User'
		})
		
		response = client.post('/auth/login', json={
			'email': unique_email,
			'password': 'test123'
		})
		assert response.status_code == 200
		data = response.get_json()
		assert 'token' in data
		assert 'user' in data


class TestLegacyEmails:
	"""Email tests using pytest fixtures"""
	
	def test_get_emails(self, client, auth_headers):
		"""Test getting emails with authentication"""
		response = client.get('/api/emails', headers=auth_headers)
		assert response.status_code == 200
		data = response.get_json()
		assert isinstance(data, list)


class TestLegacySearch:
	"""Search tests using pytest fixtures"""
	
	def test_search_emails(self, client, auth_headers):
		"""Test searching emails with authentication"""
		response = client.get('/api/search?q=test', headers=auth_headers)
		assert response.status_code == 200
		data = response.get_json()
		assert 'emails' in data
		assert isinstance(data['emails'], list)
