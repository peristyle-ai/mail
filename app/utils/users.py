from datetime import datetime, timezone
from .db import get_db_connection
from ... import mail_config as cfg  # Phase 1b: schema-qualified table names


def get_user_by_email(email):
    conn = get_db_connection()
    cursor = conn.cursor()
    # Phase 1b: schema-qualified users table
    cursor.execute(f"SELECT * FROM {cfg.users_t()} WHERE email = %s", (email,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    return user


def create_user(email, password, name):
    conn = get_db_connection()
    cursor = conn.cursor()
    # Phase 1b: schema-qualified users table
    cursor.execute(
        f"INSERT INTO {cfg.users_t()} (email, password_hash, name, is_local, created_at) "
        f"VALUES (%s, %s, %s, %s, %s) RETURNING id, email",
        (email, password, name, True, datetime.now(timezone.utc)),
    )
    user = cursor.fetchone()
    conn.commit()
    cursor.close()
    conn.close()
    return user
