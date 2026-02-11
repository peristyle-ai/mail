from flask import Blueprint, request, jsonify
from ..db import get_db_connection
from ..utils import get_user_by_email, create_user, hash_password, verify_password, generate_jwt

bp = Blueprint('auth', __name__)

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
	"""
	data = request.get_json()
	email = data.get('email')
	password = data.get('password')

	if not email or not password:
		return jsonify({'error': 'Email and password required'}), 400

	user = get_user_by_email(email)
	if not user:
		return jsonify({'error': 'Invalid credentials'}), 401

	if not verify_password(password, user['password_hash']):
		return jsonify({'error': 'Invalid credentials'}), 401

	token = generate_jwt(user['id'])

	return jsonify({'token': token, 'user': {'id': user['id'], 'email': user['email']}})
