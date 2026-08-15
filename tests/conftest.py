import os
import sys
import pytest

# ---------------------------------------------------------------------------
# Test credential configuration
#
# As of 2026-08-15, the weak hardcoded `postgres:1234` was removed because:
#   1. The actual postgres superuser password was rotated (multi-rotation event
#      this session — final prefix `S7Kz9dqV…`); hardcoding `1234` would mean
#      every pytest run needs PG rotated back, which is impossible.
#   2. The `1234` had been exposed in chat transcript 3+ times.
#
# Tests now REQUIRE the `POSTGRES_PASSWORD_TEST` env var to be set. To run tests:
#
#   POSTGRES_PASSWORD_TEST='<the postgres role pw>' pytest tests/
#
# Or for the canonical repo-wide value, see ~/credentials/postgres_credentials.md
# (rotate-chained audit log). The test DB `mail_server_test` is owned by the
# `postgres` role, so the postgres password works for tests.
# ---------------------------------------------------------------------------

_postgres_pw = os.environ.get('POSTGRES_PASSWORD_TEST')
if not _postgres_pw:
    sys.stderr.write(
        '\n'
        '====================================================================\n'
        '  py_pg_email tests require POSTGRES_PASSWORD_TEST env var.\n'
        '  See tests/conftest.py for full context.\n'
        '  Example:\n'
        '    POSTGRES_PASSWORD_TEST="<postgres role pw>" pytest tests/\n'
        '====================================================================\n'
        '\n'
    )
    sys.exit(2)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['TESTING'] = 'true'
os.environ['DATABASE_URL'] = 'postgresql://postgres:{}@localhost:5432/mail_server_test'.format(_postgres_pw)
os.environ['JWT_SECRET'] = 'test-secret-key'
os.environ['SMTP2GO_WEBHOOK_SECRET'] = ''

from app import create_app
from app.db import get_db_connection, seed_local_domains


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

	# Clean up test data but keep users for auth
	cursor.execute("DELETE FROM delivery_logs")
	cursor.execute("DELETE FROM outbound_queue")
	cursor.execute("DELETE FROM email_recipients")
	cursor.execute("DELETE FROM attachments")
	cursor.execute("DELETE FROM emails")
	cursor.execute("DELETE FROM folders")
	cursor.execute("DELETE FROM domains")
	cursor.execute("DELETE FROM ip_blacklist")
	# Note: We don't delete users here because auth_headers fixture needs them

	conn.commit()
	seed_local_domains()
	cursor.close()
	conn.close()

	return get_db_connection


@pytest.fixture
def auth_headers(client, db):
	"""Create a test user and return auth headers"""
	# First clean up any existing test user
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute("DELETE FROM users WHERE email = 'test@example.com'")
	conn.commit()
	cursor.close()
	conn.close()

	# Register new user
	response = client.post('/auth/register', json={
		'email': 'test@example.com',
		'password': 'testpassword123',
		'name': 'Test User'
	})

	# Login to get token
	response = client.post('/auth/login', json={
		'email': 'test@example.com',
		'password': 'testpassword123'
	})

	data = response.get_json()
	token = data['token']
	return {'Authorization': f'Bearer {token}'}


@pytest.fixture
def auth_headers_second_user(client, db):
	"""Create a second test user and return auth headers for cross-user security tests"""
	# First clean up any existing test user
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute("DELETE FROM users WHERE email = 'test2@example.com'")
	conn.commit()
	cursor.close()
	conn.close()

	# Register new user
	response = client.post('/auth/register', json={
		'email': 'test2@example.com',
		'password': 'testpassword456',
		'name': 'Test User 2'
	})

	# Login to get token
	response = client.post('/auth/login', json={
		'email': 'test2@example.com',
		'password': 'testpassword456'
	})

	data = response.get_json()
	token = data['token']
	return {'Authorization': f'Bearer {token}'}