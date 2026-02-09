from flask import Blueprint, request, jsonify
from .db import get_db_connection

bp = Blueprint('folders', __name__)

@bp.route('/api/folders', methods=['GET'])
def get_folders():
	user_id = request.args.get('user_id')
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute('SELECT * FROM folders WHERE user_id = %s ORDER BY name', (user_id,))
	folders = cursor.fetchall()
	cursor.close()
	conn.close()
	return jsonify([dict(f) for f in folders])

@bp.route('/api/folders', methods=['POST'])
def create_folder():
	data = request.get_json()
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute('INSERT INTO folders (user_id, name, parent_id) VALUES (%s, %s, %s) RETURNING id', (data['user_id'], data['name'], data.get('parent_id')))
	folder_id = int(cursor.fetchone()[0])
	conn.commit()
	cursor.close()
	conn.close()
	return jsonify({'id': folder_id}), 201
