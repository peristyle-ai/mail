from flask import Blueprint, request, jsonify
from app.utils.auth import token_required
from ..db import get_db_connection, ensure_domains_table
from smtp_server.outbound.smtp2go_delivery import SMTP2GODelivery
import re

bp = Blueprint('domains', __name__)

DOMAIN_RE = re.compile(r'^[A-Za-z0-9.-]+$')
VALID_RELAY_PROVIDERS = {'smtp2go', 'sendgrid', 'smtp'}


def normalize_domain(domain):
	"""Normalize and validate a domain name."""
	value = (domain or '').strip().lower().rstrip('.')
	if not value or not DOMAIN_RE.match(value):
		return None
	return value


def domain_to_dict(row):
	"""Convert a database row to a safe API response."""
	return {
		'id': row['id'],
		'domain': row['domain'],
		'relay_provider': row['relay_provider'],
		'relay_host': row['relay_host'],
		'relay_port': row['relay_port'],
		'relay_username': row['relay_username'],
		'relay_from_address': row['relay_from_address'],
		'relay_verified': row['relay_verified'],
		'relay_verified_at': row['relay_verified_at'],
		'spf_verified': row['spf_verified'],
		'dkim_verified': row['dkim_verified'],
		'has_password': bool(row['relay_password_encrypted']),
		'created_at': row['created_at'],
		'updated_at': row['updated_at'],
	}


@bp.route('/api/domains', methods=['GET'])
@token_required
def list_domains():
	"""
	List configured domains
	---
	tags:
	  - Domains
	security:
	  - Bearer: []
	responses:
	  200:
	    description: List of domains and relay settings
	  401:
	    description: Unauthorized
	"""
	ensure_domains_table()
	conn = get_db_connection()
	cursor = conn.cursor()
	try:
		cursor.execute(
			'''SELECT id, domain, relay_provider, relay_host, relay_port,
			   relay_username, relay_password_encrypted, relay_from_address,
			   relay_verified, relay_verified_at, spf_verified, dkim_verified,
			   created_at, updated_at
			   FROM domains
			   ORDER BY domain'''
		)
		rows = cursor.fetchall()
		return jsonify({'domains': [domain_to_dict(row) for row in rows]})
	finally:
		cursor.close()
		conn.close()


@bp.route('/api/domains/<domain>', methods=['GET'])
@token_required
def get_domain(domain):
	"""
	Get one domain configuration
	---
	tags:
	  - Domains
	security:
	  - Bearer: []
	responses:
	  200:
	    description: Domain settings
	  401:
	    description: Unauthorized
	  404:
	    description: Domain not found
	"""
	ensure_domains_table()
	domain_name = normalize_domain(domain)
	if not domain_name:
		return jsonify({'error': 'Invalid domain'}), 400

	conn = get_db_connection()
	cursor = conn.cursor()
	try:
		cursor.execute(
			'''SELECT id, domain, relay_provider, relay_host, relay_port,
			   relay_username, relay_password_encrypted, relay_from_address,
			   relay_verified, relay_verified_at, spf_verified, dkim_verified,
			   created_at, updated_at
			   FROM domains WHERE domain = %s''',
			(domain_name,)
		)
		row = cursor.fetchone()
		if not row:
			return jsonify({'error': 'Domain not found'}), 404
		return jsonify(domain_to_dict(row))
	finally:
		cursor.close()
		conn.close()


@bp.route('/api/domains/<domain>/relay', methods=['PUT'])
@token_required
def set_domain_relay(domain):
	"""
	Create or update relay credentials for a domain
	---
	tags:
	  - Domains
	security:
	  - Bearer: []
	responses:
	  200:
	    description: Relay settings saved
	  400:
	    description: Invalid request
	  401:
	    description: Unauthorized
	"""
	ensure_domains_table()
	domain_name = normalize_domain(domain)
	if not domain_name:
		return jsonify({'error': 'Invalid domain'}), 400

	data = request.get_json() or {}
	provider = (data.get('relay_provider') or '').strip().lower()
	host = (data.get('relay_host') or '').strip()
	username = (data.get('relay_username') or '').strip()
	password = (data.get('relay_password') or '').strip()
	from_address = (data.get('relay_from_address') or '').strip().lower()
	port = data.get('relay_port')

	if provider not in VALID_RELAY_PROVIDERS:
		return jsonify({'error': 'relay_provider must be one of smtp2go, sendgrid, smtp'}), 400
	if not username or not password:
		return jsonify({'error': 'relay_username and relay_password are required'}), 400
	if not host:
		host = 'mail-au.smtp2go.com' if provider == 'smtp2go' else ''
	if not host:
		return jsonify({'error': 'relay_host is required for this provider'}), 400
	if port is None:
		port = 2525 if provider == 'smtp2go' else 587
	try:
		port = int(port)
	except (TypeError, ValueError):
		return jsonify({'error': 'relay_port must be an integer'}), 400

	conn = get_db_connection()
	cursor = conn.cursor()
	try:
		cursor.execute(
			'''INSERT INTO domains (
			   domain, relay_provider, relay_host, relay_port,
			   relay_username, relay_password_encrypted, relay_from_address,
			   relay_verified, relay_verified_at, updated_at
			   ) VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE, NULL, CURRENT_TIMESTAMP)
			   ON CONFLICT (domain) DO UPDATE SET
			   relay_provider = EXCLUDED.relay_provider,
			   relay_host = EXCLUDED.relay_host,
			   relay_port = EXCLUDED.relay_port,
			   relay_username = EXCLUDED.relay_username,
			   relay_password_encrypted = EXCLUDED.relay_password_encrypted,
			   relay_from_address = EXCLUDED.relay_from_address,
			   relay_verified = FALSE,
			   relay_verified_at = NULL,
			   updated_at = CURRENT_TIMESTAMP
			   RETURNING id, domain, relay_provider, relay_host, relay_port,
			   relay_username, relay_password_encrypted, relay_from_address,
			   relay_verified, relay_verified_at, spf_verified, dkim_verified,
			   created_at, updated_at''',
			(domain_name, provider, host, port, username, password, from_address or None)
		)
		row = cursor.fetchone()
		conn.commit()
		return jsonify({
			**domain_to_dict(row),
			'message': 'Relay credentials saved. Verify them before relying on relay delivery.'
		})
	finally:
		cursor.close()
		conn.close()


@bp.route('/api/domains/<domain>/relay/verify', methods=['POST'])
@token_required
def verify_domain_relay(domain):
	"""
	Verify relay credentials by connecting and authenticating
	---
	tags:
	  - Domains
	security:
	  - Bearer: []
	responses:
	  200:
	    description: Relay verified
	  400:
	    description: Relay verification failed
	  401:
	    description: Unauthorized
	  404:
	    description: Domain not found
	"""
	ensure_domains_table()
	domain_name = normalize_domain(domain)
	if not domain_name:
		return jsonify({'error': 'Invalid domain'}), 400

	conn = get_db_connection()
	cursor = conn.cursor()
	try:
		cursor.execute(
			'''SELECT id, domain, relay_provider, relay_host, relay_port,
			   relay_username, relay_password_encrypted, relay_from_address,
			   relay_verified, relay_verified_at, spf_verified, dkim_verified,
			   created_at, updated_at
			   FROM domains WHERE domain = %s''',
			(domain_name,)
		)
		row = cursor.fetchone()
		if not row:
			return jsonify({'error': 'Domain not found'}), 404
		if not row['relay_provider'] or not row['relay_username'] or not row['relay_password_encrypted']:
			return jsonify({'error': 'Relay credentials are not configured for this domain'}), 400

		relay_client = SMTP2GODelivery(
			relay_host=row['relay_host'] or 'mail-au.smtp2go.com',
			relay_port=row['relay_port'] or 2525,
			username=row['relay_username'],
			password=row['relay_password_encrypted']
		)
		success, message = relay_client.verify_connection()
		if not success:
			return jsonify({'success': False, 'error': message}), 400

		cursor.execute(
			'''UPDATE domains
			   SET relay_verified = TRUE,
			       relay_verified_at = CURRENT_TIMESTAMP,
			       updated_at = CURRENT_TIMESTAMP
			   WHERE domain = %s''',
			(domain_name,)
		)
		conn.commit()

		cursor.execute(
			'''SELECT id, domain, relay_provider, relay_host, relay_port,
			   relay_username, relay_password_encrypted, relay_from_address,
			   relay_verified, relay_verified_at, spf_verified, dkim_verified,
			   created_at, updated_at
			   FROM domains WHERE domain = %s''',
			(domain_name,)
		)
		verified_row = cursor.fetchone()
		return jsonify({
			'success': True,
			'message': message,
			'domain': domain_to_dict(verified_row)
		})
	finally:
		cursor.close()
		conn.close()


@bp.route('/api/domains/<domain>/relay', methods=['DELETE'])
@token_required
def delete_domain_relay(domain):
	"""
	Remove relay configuration from a domain
	---
	tags:
	  - Domains
	security:
	  - Bearer: []
	responses:
	  200:
	    description: Relay removed
	  401:
	    description: Unauthorized
	  404:
	    description: Domain not found
	"""
	ensure_domains_table()
	domain_name = normalize_domain(domain)
	if not domain_name:
		return jsonify({'error': 'Invalid domain'}), 400

	conn = get_db_connection()
	cursor = conn.cursor()
	try:
		cursor.execute(
			'''UPDATE domains
			   SET relay_provider = NULL,
			       relay_host = NULL,
			       relay_port = 2525,
			       relay_username = NULL,
			       relay_password_encrypted = NULL,
			       relay_from_address = NULL,
			       relay_verified = FALSE,
			       relay_verified_at = NULL,
			       updated_at = CURRENT_TIMESTAMP
			   WHERE domain = %s
			   RETURNING id, domain, relay_provider, relay_host, relay_port,
			   relay_username, relay_password_encrypted, relay_from_address,
			   relay_verified, relay_verified_at, spf_verified, dkim_verified,
			   created_at, updated_at''',
			(domain_name,)
		)
		row = cursor.fetchone()
		if not row:
			return jsonify({'error': 'Domain not found'}), 404
		conn.commit()
		return jsonify({
			'success': True,
			'message': 'Relay credentials removed',
			'domain': domain_to_dict(row)
		})
	finally:
		cursor.close()
		conn.close()
