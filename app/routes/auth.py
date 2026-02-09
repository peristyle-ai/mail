from flask import Blueprint, request, jsonify
from app.db import get_db_connection
from app.utils import get_user_by_email, create_user, hash_password, generate_jwt

bp = Blueprint('auth', __name__)

@bp.route('/auth/register', methods=['POST'])
def register():
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
	data = request.get_json()
	email = data.get('email')
	password = data.get('password')

	if not email or not password:
		return jsonify({'error': 'Email and password required'}), 400

	user = get_user_by_email(email)
	if not user:
		return jsonify({'error': 'Invalid credentials'}), 401

	if hash_password(password) != user['password_hash']:
		return jsonify({'error': 'Invalid credentials'}), 401

	token = generate_jwt(user['id'])

	return jsonify({'token': token, 'user': {'id': user['id'], 'email': user['email']}})
