import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['TESTING'] = 'true'
os.environ['DATABASE_URL'] = 'postgresql://postgres:1234@localhost:5432/mail_server_test'
os.environ['JWT_SECRET'] = 'test-secret-key'

from app import create_app
from app.db import get_db_connection


@pytest.fixture
def app():
	app = create_app()
	app.config['TESTING'] = True
	app.config['JWT_SECRET'] = 'test-secret-key'
	return app


@pytest.fixture
def client(app):
	return app.test_client()


@pytest.fixture
def db():
	conn = get_db_connection()
	cursor = conn.cursor()
	
	cursor.execute("DELETE FROM email_recipients")
	cursor.execute("DELETE FROM attachments")
	cursor.execute("DELETE FROM emails")
	cursor.execute("DELETE FROM folders")
	cursor.execute("DELETE FROM users")
	
	conn.commit()
	cursor.close()
	conn.close()
	
	return get_db_connection


@pytest.fixture
def auth_headers(client):
	"""Create a test user and return auth headers"""
	response = client.post('/auth/register', json={
		'email': 'test@example.com',
		'password': 'testpassword123',
		'name': 'Test User'
	})
	
	response = client.post('/auth/login', json={
		'email': 'test@example.com',
		'password': 'testpassword123'
	})
	
	data = response.get_json()
	token = data['token']
	return {'Authorization': f'Bearer {token}'}


@pytest.fixture
def auth_headers_second_user(client):
	"""Create a second test user and return auth headers for cross-user security tests"""
	response = client.post('/auth/register', json={
		'email': 'test2@example.com',
		'password': 'testpassword456',
		'name': 'Test User 2'
	})
	
	response = client.post('/auth/login', json={
		'email': 'test2@example.com',
		'password': 'testpassword456'
	})
	
	data = response.get_json()
	token = data['token']
	return {'Authorization': f'Bearer {token}'}
