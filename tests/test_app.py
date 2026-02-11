import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['TESTING'] = 'true'
os.environ['DATABASE_URL'] = 'postgresql://postgres:1234@localhost:5432/mail_server_test'

from app import create_app
from app.db import get_db_connection


class MailServerTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        
    def tearDown(self):
        pass


class AuthTestCase(MailServerTestCase):
    def test_register_user(self):
        response = self.client.post('/auth/register', json={
            'email': 'test@example.com',
            'password': 'test123',
            'name': 'Test User'
        })
        self.assertEqual(response.status_code, 201)
        data = response.get_json()
        self.assertIn('id', data)
        self.assertIn('email', data)
        self.assertEqual(data['email'], 'test@example.com')

    def test_login_user(self):
        self.client.post('/auth/register', json={
            'email': 'test@example.com',
            'password': 'test123',
            'name': 'Test User'
        })
        
        response = self.client.post('/auth/login', json={
            'email': 'test@example.com',
            'password': 'test123'
        })
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn('token', data)
        self.assertIn('user', data)


class EmailTestCase(MailServerTestCase):
    def test_get_emails(self):
        response = self.client.get('/api/emails')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIsInstance(data, list)


class SearchTestCase(MailServerTestCase):
    def test_search_emails(self):
        response = self.client.get('/api/search?q=test')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIsInstance(data, list)


if __name__ == '__main__':
    unittest.main()
