from flask import Blueprint, request, jsonify
from .db import get_db_connection

bp = Blueprint('search', __name__)

@bp.route('/api/search', methods=['GET'])
def search_emails():
	query = request.args.get('q', '')
	folder_id = request.args.get('folder_id')
	flag = request.args.get('flag')

	conn = get_db_connection()
	cursor = conn.cursor()

	sql = 'SELECT * FROM emails WHERE 1=1'
	params = []

	if query:
		sql += ' AND (subject ILIKE %s OR body ILIKE %s)'
		params.extend(['%' + query + '%', '%' + query + '%'])

	if folder_id:
		sql += ' AND folder_id = %s'
		params.append(folder_id)

	if flag == 'read':
		sql += ' AND is_read = TRUE'
	elif flag == 'unread':
		sql += ' AND is_read = FALSE'
	elif flag == 'starred':
		sql += ' AND is_starred = TRUE'

	sql += ' ORDER BY created_at DESC'

	cursor.execute(sql, params)
	emails = cursor.fetchall()
	cursor.close()
	conn.close()
	return jsonify([dict(e) for e in emails])