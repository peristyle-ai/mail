import time

from flask import Blueprint, request, jsonify
from ..db import get_db_connection
from ..utils import get_user_by_email, create_user, hash_password, verify_password, generate_jwt
from ..utils.rate_limiter import check_rate_limit, record_attempt, clear_attempts

bp = Blueprint('auth', __name__)

FAILED_LOGIN_WINDOW_SECONDS = 15 * 60
FAILED_LOGIN_LIMIT_PER_IP = 20
FAILED_LOGIN_LIMIT_PER_IP_EMAIL = 5


def _normalize_email(email):
	return (email or '').strip().lower()


def _get_login_keys(client_ip, email):
	normalized_email = _normalize_email(email)
	keys = [(f'ip:{client_ip}', FAILED_LOGIN_LIMIT_PER_IP)]
	if normalized_email:
		keys.append((f'combo:{client_ip}:{normalized_email}', FAILED_LOGIN_LIMIT_PER_IP_EMAIL))
	return keys


def _record_login_failure(client_ip, email):
	for key, limit in _get_login_keys(client_ip, email):
		record_attempt(key)


def _clear_login_failures(client_ip, email):
	for key, _ in _get_login_keys(client_ip, email):
		clear_attempts(key)


def _is_request_locked(client_ip, email):
	for key, limit in _get_login_keys(client_ip, email):
		allowed, reason = check_rate_limit(key, limit, FAILED_LOGIN_WINDOW_SECONDS)
		if not allowed:
			return True
	return False

@bp.route('/auth/register', methods=['POST'])
def register():
	"""
	Register a new user
	---
	tags:
	  - Authentication
	parameters:
	  - in: body
	    name: body
	    schema:
	      type: object
	      required:
	        - email
	        - password
	      properties:
	        email:
	          type: string
	          description: User's email address
	        password:
	          type: string
	          description: User's password
	        name:
	          type: string
	          description: User's display name
	responses:
	  201:
	    description: User created successfully
	    schema:
	      type: object
	      properties:
	        id:
	          type: integer
	        email:
	          type: string
	  400:
	    description: Missing required fields
	  409:
	    description: User already exists
	"""
	data = request.get_json()
	email = data.get('email')
	password = data.get('password')
	name = data.get('name')

	if not email or not password:
		return jsonify({'error': 'Email and password required'}), 400

	if get_user_by_email(email):
		return jsonify({'error': 'User already exists'}), 409

	password_hash = hash_password(password)
	user_id = create_user(email, password_hash, name)

	return jsonify({'id': user_id, 'email': email}), 201

@bp.route('/auth/login', methods=['POST'])
def login():
	"""
	Login and get JWT token
	---
	tags:
	  - Authentication
	parameters:
	  - in: body
	    name: body
	    schema:
	      type: object
	      required:
	        - email
	        - password
	      properties:
	        email:
	          type: string
	          description: User's email address
	        password:
	          type: string
	          description: User's password
	responses:
	  200:
	    description: Login successful
	    schema:
	      type: object
	      properties:
	        token:
	          type: string
	          description: JWT token for authentication
	        user:
	          type: object
	          properties:
	            id:
	              type: integer
	            email:
	              type: string
	  400:
	    description: Missing required fields
	  401:
	    description: Invalid credentials
	  429:
	    description: Too many failed login attempts
	"""
	data = request.get_json() or {}
	email = data.get('email')
	password = data.get('password')
	client_ip = request.remote_addr or 'unknown'

	if not email or not password:
		return jsonify({'error': 'Email and password required'}), 400

	if _is_request_locked(client_ip, email):
		return jsonify({'error': 'Too many login attempts. Try again later.'}), 429

	user = get_user_by_email(email)
	if not user:
		_record_login_failure(client_ip, email)
		return jsonify({'error': 'Invalid credentials'}), 401

	if not verify_password(password, user['password_hash']):
		_record_login_failure(client_ip, email)
		return jsonify({'error': 'Invalid credentials'}), 401

	_clear_login_failures(client_ip, email)

	token = generate_jwt(user['id'])

	return jsonify({'token': token, 'user': {'id': user['id'], 'email': user['email'], 'timezone': user.get('timezone', 'Australia/Sydney')}})
