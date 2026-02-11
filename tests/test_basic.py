import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['TESTING'] = 'true'
os.environ['DATABASE_URL'] = 'postgresql://postgres:1234@localhost:5432/mail_server'


@pytest.fixture
def client():
    from app import create_app
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def test_app_exists(client):
    response = client.get('/api/emails')
    assert response.status_code == 200


def test_auth_routes_exist(client):
    response = client.post('/auth/register', json={'email': 'test@test.com', 'password': 'test123', 'name': 'Test'})
    assert response.status_code in [200, 201, 409]
