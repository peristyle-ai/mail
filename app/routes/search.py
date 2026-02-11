from flask import Blueprint, request, jsonify
from ..db import get_db_connection
from app.utils.auth import token_required

bp = Blueprint('search', __name__)

@bp.route('/api/search', methods=['GET'])
@token_required
def search_emails():
    query = request.args.get('q', '')
    folder_id = request.args.get('folder_id')
    flag = request.args.get('flag')
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 20, type=int)

    conn = get_db_connection()
    cursor = conn.cursor()

    sql = 'SELECT * FROM emails WHERE user_id = %s'
    params = [request.current_user['id']]

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
    sql += ' LIMIT %s OFFSET %s'
    params.extend([limit, (page - 1) * limit])

    cursor.execute(sql, params)
    emails = cursor.fetchall()
    
    cursor.execute('SELECT COUNT(*) as total FROM emails WHERE user_id = %s', [request.current_user['id']])
    total = cursor.fetchone()['total']
    
    cursor.close()
    conn.close()
    
    return jsonify({
        'emails': [dict(e) for e in emails],
        'total': total,
        'page': page,
        'limit': limit
    })
