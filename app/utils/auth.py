import os
import jwt
import hashlib
from datetime import datetime, timedelta, timezone
from functools import wraps
from flask import request, jsonify
from .db import get_db_connection

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password, password_hash):
    return hash_password(password) == password_hash

def generate_jwt(user_id):
    secret_key = os.getenv('JWT_SECRET', 'dev-secret-key')
    now = datetime.now(timezone.utc)
    payload = {
        'user_id': user_id,
        'exp': now + timedelta(hours=24),
        'iat': now
    }
    return jwt.encode(payload, secret_key, algorithm='HS256')

def decode_jwt(token):
    secret_key = os.getenv('JWT_SECRET', 'dev-secret-key')
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

        request.current_user = current_user
        return f(*args, **kwargs)

    return decorated
