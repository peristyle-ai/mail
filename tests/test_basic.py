import pytest
import uuid


def test_app_exists(client, auth_headers):
	"""Test that the app exists and responds to authenticated requests"""
	response = client.get('/api/emails', headers=auth_headers)
	assert response.status_code == 200


def test_auth_routes_exist(client, db):
	"""Test that auth routes exist and work"""
	unique_email = f'basic_test_{uuid.uuid4().hex[:8]}@example.com'
	response = client.post('/auth/register', json={
		'email': unique_email,
		'password': 'test123',
		'name': 'Test'
	})
	assert response.status_code in [200, 201, 409]
