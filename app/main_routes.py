from flask import Blueprint, request, jsonify, send_file
from .db import get_db_connection
import os

bp = Blueprint('routes', __name__)

@bp.route('/health', methods=['GET'])
def health():
	return jsonify({'status': 'ok'})

@bp.route('/ca.crt', methods=['GET'])
def ca_cert():
	"""Serve the TLS certificate for client trust-store installation.
	
	Agents on other machines can fetch this once and install it into their
	system CA store to trust the self-signed cert without disabling verification.
	"""
	cert_path = os.path.join(
		os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
		'certs', 'server.crt'
	)
	if not os.path.exists(cert_path):
		return jsonify({'error': 'TLS not configured'}), 404
	return send_file(cert_path, mimetype='application/x-x509-ca-cert',
	                 as_attachment=True, download_name='py_pg_email.crt')
