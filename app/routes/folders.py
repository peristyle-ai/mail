from flask import Blueprint, request, jsonify
from ..db import get_db_connection
from app.utils.auth import token_required

bp = Blueprint('folders', __name__)

@bp.route('/api/folders', methods=['GET'])
@token_required
def get_folders():
	"""
	List all folders for authenticated user
	---
	tags:
	  - Folders
	security:
	  - Bearer: []
	responses:
	  200:
	    description: List of folders
	    schema:
	      type: array
	      items:
	        type: object
	        properties:
	          id:
	            type: integer
	          name:
	            type: string
	          parent_id:
	            type: integer
	  401:
	    description: Unauthorized
	"""
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute('SELECT * FROM folders WHERE user_id = %s ORDER BY name', (request.current_user['id'],))
	folders = cursor.fetchall()
	cursor.close()
	conn.close()
	return jsonify([dict(f) for f in folders])

@bp.route('/api/folders', methods=['POST'])
@token_required
def create_folder():
	"""
	Create a new folder
	---
	tags:
	  - Folders
	security:
	  - Bearer: []
	parameters:
	  - in: body
	    name: body
	    schema:
	      type: object
	      required:
	        - name
	      properties:
	        name:
	          type: string
	          description: Folder name
	        parent_id:
	          type: integer
	          description: Parent folder ID (optional)
	responses:
	  201:
	    description: Folder created successfully
	    schema:
	      type: object
	      properties:
	        id:
	          type: integer
	  401:
	    description: Unauthorized
	"""
	data = request.get_json()
	conn = get_db_connection()
	cursor = conn.cursor()
	cursor.execute('INSERT INTO folders (user_id, name, parent_id) VALUES (%s, %s, %s) RETURNING id', (request.current_user['id'], data['name'], data.get('parent_id')))
	folder_id = cursor.fetchone()['id']
	conn.commit()
	cursor.close()
	conn.close()
	return jsonify({'id': folder_id}), 201
