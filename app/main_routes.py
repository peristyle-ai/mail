from flask import Blueprint, request, jsonify
from .db import get_db_connection

bp = Blueprint('routes', __name__)

@bp.route('/health', methods=['GET'])
def health():
	return jsonify({'status': 'ok'})
