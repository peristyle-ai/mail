"""The accounts' default timezone must be Australia/Brisbane.

The `users.timezone` column defaulted to 'Australia/Sydney'. Brisbane is
UTC+10 all year; Sydney is UTC+11 for roughly half the year. The webmail
client renders every timestamp in the account's timezone, so from late
September to early April every time in the UI -- and every quoted
"On <date>" line in a sent reply -- was an hour ahead of the real local
time.

There is no endpoint that lets a user set a timezone, so the column
default is effectively the only value most accounts ever had. Fixing the
default alone is not enough: existing rows keep whatever they were
created with, which is why migration 008 also updates them.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


EXPECTED_TIMEZONE = 'Australia/Brisbane'


def _remove_test_user(db, email):
    """The `db` fixture does not delete users, so a registration left over
    from an earlier run would make this test fail with 409. Start clean."""
    conn = db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE email = %s", (email,))
    conn.commit()
    cursor.close()
    conn.close()


def test_users_column_default_is_brisbane(db):
    """A newly inserted user must land on Brisbane without any code help."""
    conn = db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT column_default FROM information_schema.columns "
        "WHERE table_name = 'users' AND column_name = 'timezone'"
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    assert row is not None, "users.timezone column is missing"
    assert EXPECTED_TIMEZONE in row['column_default'], row['column_default']


def test_registered_user_gets_brisbane(client, db):
    """Registration must not have to set the timezone explicitly."""
    _remove_test_user(db, 'timezone-test@example.test')
    response = client.post('/auth/register', json={
        'email': 'timezone-test@example.test',
        'password': os.environ.get('MAIL_TEST_PASSWORD', 'not-a-real-password'),
        'name': 'Timezone Test',
    })
    assert response.status_code in (200, 201), response.get_data(as_text=True)

    conn = db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT timezone FROM users WHERE email = %s", ('timezone-test@example.test',)
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    assert row is not None, "registered user not found"
    assert row['timezone'] == EXPECTED_TIMEZONE, row['timezone']


def test_login_response_carries_brisbane(client, db):
    """The client takes its timezone from the login response."""
    _remove_test_user(db, 'timezone-login-test@example.test')
    client.post('/auth/register', json={
        'email': 'timezone-login-test@example.test',
        'password': os.environ.get('MAIL_TEST_PASSWORD', 'not-a-real-password'),
        'name': 'Timezone Login Test',
    })
    response = client.post('/auth/login', json={
        'email': 'timezone-login-test@example.test',
        'password': os.environ.get('MAIL_TEST_PASSWORD', 'not-a-real-password'),
    })
    assert response.status_code == 200, response.get_data(as_text=True)
    data = response.get_json()
    assert data['user']['timezone'] == EXPECTED_TIMEZONE, data['user']
