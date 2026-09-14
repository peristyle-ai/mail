import os
import jwt
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from ..db import get_db_connection, set_current_user_id

def hash_password(password):
    return generate_password_hash(password, method='pbkdf2:sha256')

def verify_password(password, password_hash):
    return check_password_hash(password_hash, password)

def _get_jwt_secret():
    secret_key = os.getenv('JWT_SECRET')
    if not secret_key:
        raise RuntimeError("JWT_SECRET environment variable is required. Set it in .env")
    return secret_key

def generate_jwt(user_id):
    secret_key = _get_jwt_secret()
    now = datetime.now(timezone.utc)
    payload = {
        'user_id': user_id,
        'exp': now + timedelta(hours=24),
        'iat': now
    }
    return jwt.encode(payload, secret_key, algorithm='HS256')

def decode_jwt(token):
    secret_key = _get_jwt_secret()
    return jwt.decode(token, secret_key, algorithms=['HS256'])

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            if auth_header.startswith('Bearer '):
                token = auth_header[7:]

        if not token:
            return jsonify({'error': 'Token is missing'}), 401

        try:
            data = decode_jwt(token)
            current_user_id = data['user_id']
        except Exception:
            return jsonify({'error': 'Token is invalid'}), 401

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE id = %s', (current_user_id,))
        current_user = cursor.fetchone()
        cursor.close()
        conn.close()

        if not current_user:
            return jsonify({'error': 'User not found'}), 401

        # Set thread-local user ID so get_db_connection() can set the RLS GUC
        set_current_user_id(current_user_id)

        request.current_user = current_user
        return f(*args, **kwargs)

    return decorated
