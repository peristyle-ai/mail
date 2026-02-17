"""
IP Blacklist API Routes

Provides REST API for managing IP blacklist entries.
All endpoints require JWT authentication.
"""

from flask import Blueprint, request, jsonify
from app.utils.auth import token_required
from ..db import get_db_connection
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)
bp = Blueprint('blacklist', __name__)


def normalize_ip(ip_str):
	"""Normalize IP address string by removing CIDR suffix from IPv6"""
	if ip_str and '/' in ip_str:
		return ip_str.split('/')[0]
	return ip_str


@bp.route('/api/blacklist/ip', methods=['GET'])
@token_required
def list_blacklisted_ips():
	"""
	List all blacklisted IP addresses
	---
	tags:
	  - Blacklist
	security:
	  - Bearer: []
	parameters:
	  - in: query
	    name: source
	    type: string
	    description: Filter by source (manual, auto_spf_fail, auto_rate_limit, dnsbl)
	  - in: query
	    name: active_only
	    type: boolean
	    default: true
	    description: Only show non-expired entries
	  - in: query
	    name: page
	    type: integer
	    default: 1
	    description: Page number
	  - in: query
	    name: limit
	    type: integer
	    default: 20
	    description: Results per page
	responses:
	  200:
	    description: List of blacklisted IPs
	    schema:
	      type: object
	      properties:
	        blacklisted_ips:
	          type: array
	          items:
	            type: object
	            properties:
	              id:
	                type: integer
	              ip_address:
	                type: string
	              reason:
	                type: string
	              source:
	                type: string
	              expires_at:
	                type: string
	                format: date-time
	              hit_count:
	                type: integer
	              created_at:
	                type: string
	                format: date-time
	        total:
	          type: integer
	        page:
	          type: integer
	        limit:
	          type: integer
	  401:
	    description: Unauthorized
	"""
	conn = get_db_connection()
	cursor = conn.cursor()
	
	# Get query parameters
	source_filter = request.args.get('source')
	active_only = request.args.get('active_only', 'true').lower() == 'true'
	page = request.args.get('page', 1, type=int)
	limit = request.args.get('limit', 20, type=int)
	
	# Build query
	params = []
	where_clauses = []
	
	if source_filter:
		where_clauses.append('source = %s')
		params.append(source_filter)
	
	if active_only:
		where_clauses.append('(expires_at IS NULL OR expires_at > %s)')
		params.append(datetime.now(timezone.utc))
	
	where_sql = ' WHERE ' + ' AND '.join(where_clauses) if where_clauses else ''
	
	# Get total count
	count_sql = f'SELECT COUNT(*) as total FROM ip_blacklist{where_sql}'
	cursor.execute(count_sql, params)
	total = cursor.fetchone()['total']
	
	# Get paginated results
	offset = (page - 1) * limit
	query_sql = f'''
		SELECT id, ip_address::text as ip_address, reason, source, 
		       expires_at, hit_count, created_at
		FROM ip_blacklist
		{where_sql}
		ORDER BY created_at DESC
		LIMIT %s OFFSET %s
	'''
	cursor.execute(query_sql, params + [limit, offset])
	
	results = cursor.fetchall()
	cursor.close()
	conn.close()
	
	# Normalize IP addresses in results
	blacklisted_ips = []
	for row in results:
		entry = dict(row)
		entry['ip_address'] = normalize_ip(entry['ip_address'])
		blacklisted_ips.append(entry)
	
	return jsonify({
		'blacklisted_ips': blacklisted_ips,
		'total': total,
		'page': page,
		'limit': limit
	})


@bp.route('/api/blacklist/ip', methods=['POST'])
@token_required
def add_ip_to_blacklist():
	"""
	Add an IP address to the blacklist
	---
	tags:
	  - Blacklist
	security:
	  - Bearer: []
	parameters:
	  - in: body
	    name: body
	    required: true
	    schema:
	      type: object
	      required:
	        - ip_address
	      properties:
	        ip_address:
	          type: string
	          description: IP address to blacklist (IPv4 or IPv6)
	          example: "192.168.1.100"
	        reason:
	          type: string
	          description: Reason for blacklisting
	          example: "Repeated spam attempts"
	        source:
	          type: string
	          description: Source of blacklist entry
	          enum: [manual, auto_spf_fail, auto_rate_limit, dnsbl]
	          default: manual
	        expires_at:
	          type: string
	          format: date-time
	          description: Expiration time (ISO 8601). Omit for permanent.
	          example: "2026-02-16T00:00:00Z"
	responses:
	  201:
	    description: IP added to blacklist
	    schema:
	      type: object
	      properties:
	        id:
	          type: integer
	        ip_address:
	          type: string
	        reason:
	          type: string
	        source:
	          type: string
	        expires_at:
	          type: string
	          format: date-time
	        created_at:
	          type: string
	          format: date-time
	  400:
	    description: Invalid IP address or already blacklisted
	  401:
	    description: Unauthorized
	"""
	data = request.get_json()
	
	if not data or 'ip_address' not in data:
		return jsonify({'error': 'ip_address is required'}), 400
	
	ip_address = data['ip_address']
	reason = data.get('reason', '')
	source = data.get('source', 'manual')
	expires_at = data.get('expires_at')
	
	# Validate source
	valid_sources = ['manual', 'auto_spf_fail', 'auto_rate_limit', 'dnsbl']
	if source not in valid_sources:
		return jsonify({'error': f'Invalid source. Must be one of: {", ".join(valid_sources)}'}), 400
	
	conn = get_db_connection()
	cursor = conn.cursor()
	
	try:
		# Parse expires_at if provided
		expires = None
		if expires_at:
			try:
				expires = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
			except ValueError:
				return jsonify({'error': 'Invalid expires_at format. Use ISO 8601 format.'}), 400
		
		# Insert into blacklist
		cursor.execute('''
			INSERT INTO ip_blacklist (ip_address, reason, source, expires_at, created_by)
			VALUES (%s::inet, %s, %s, %s, %s)
			ON CONFLICT (ip_address) DO UPDATE SET
				reason = EXCLUDED.reason,
				source = EXCLUDED.source,
				expires_at = EXCLUDED.expires_at,
				created_by = EXCLUDED.created_by,
				created_at = CURRENT_TIMESTAMP
			RETURNING id, ip_address::text, reason, source, expires_at, hit_count, created_at
		''', (ip_address, reason, source, expires, request.current_user['id']))
		
		result = cursor.fetchone()
		conn.commit()
		
		logger.info(f"IP {ip_address} added to blacklist by user {request.current_user['id']}")
		
		return jsonify({
			'id': result['id'],
			'ip_address': normalize_ip(result['ip_address']),
			'reason': result['reason'],
			'source': result['source'],
			'expires_at': result['expires_at'].isoformat() if result['expires_at'] else None,
			'hit_count': result['hit_count'],
			'created_at': result['created_at'].isoformat()
		}), 201
		
	except Exception as e:
		conn.rollback()
		logger.error(f"Error adding IP to blacklist: {e}")
		return jsonify({'error': 'Invalid IP address format'}), 400
	finally:
		cursor.close()
		conn.close()


@bp.route('/api/blacklist/ip/<int:entry_id>', methods=['DELETE'])
@token_required
def remove_blacklisted_ip(entry_id):
	"""
	Remove an IP address from the blacklist by entry ID
	---
	tags:
	  - Blacklist
	security:
	  - Bearer: []
	parameters:
	  - in: path
	    name: entry_id
	    type: integer
	    required: true
	    description: Blacklist entry ID
	responses:
	  200:
	    description: IP removed from blacklist
	    schema:
	      type: object
	      properties:
	        status:
	          type: string
	          example: removed
	        ip_address:
	          type: string
	  404:
	    description: Blacklist entry not found
	  401:
	    description: Unauthorized
	"""
	conn = get_db_connection()
	cursor = conn.cursor()
	
	# Get the IP address before deleting
	cursor.execute(
		'SELECT ip_address::text FROM ip_blacklist WHERE id = %s',
		(entry_id,)
	)
	result = cursor.fetchone()
	
	if not result:
		cursor.close()
		conn.close()
		return jsonify({'error': 'Blacklist entry not found'}), 404
	
	ip_address = normalize_ip(result['ip_address'])
	
	# Delete the entry
	cursor.execute('DELETE FROM ip_blacklist WHERE id = %s', (entry_id,))
	conn.commit()
	cursor.close()
	conn.close()
	
	logger.info(f"IP {ip_address} (entry {entry_id}) removed from blacklist by user {request.current_user['id']}")
	
	return jsonify({
		'status': 'removed',
		'ip_address': ip_address
	})


@bp.route('/api/blacklist/ip/address/<ip_address>', methods=['DELETE'])
@token_required
def remove_blacklisted_ip_by_address(ip_address):
	"""
	Remove an IP address from the blacklist by IP address (convenience endpoint)
	---
	tags:
	  - Blacklist
	security:
	  - Bearer: []
	parameters:
	  - in: path
	    name: ip_address
	    type: string
	    required: true
	    description: IP address to remove from blacklist
	    example: "192.168.1.100"
	responses:
	  200:
	    description: IP removed from blacklist
	    schema:
	      type: object
	      properties:
	        status:
	          type: string
	          example: removed
	        ip_address:
	          type: string
	  404:
	    description: IP address not found in blacklist
	  401:
	    description: Unauthorized
	"""
	conn = get_db_connection()
	cursor = conn.cursor()
	
	# Delete the entry
	cursor.execute(
		'DELETE FROM ip_blacklist WHERE ip_address = %s::inet RETURNING id',
		(ip_address,)
	)
	result = cursor.fetchone()
	
	if not result:
		cursor.close()
		conn.close()
		return jsonify({'error': 'IP address not found in blacklist'}), 404
	
	conn.commit()
	cursor.close()
	conn.close()
	
	logger.info(f"IP {ip_address} removed from blacklist by user {request.current_user['id']}")
	
	return jsonify({
		'status': 'removed',
		'ip_address': ip_address
	})


@bp.route('/api/blacklist/ip/check/<ip_address>', methods=['GET'])
@token_required
def check_ip_blacklisted(ip_address):
	"""
	Check if an IP address is blacklisted
	---
	tags:
	  - Blacklist
	security:
	  - Bearer: []
	parameters:
	  - in: path
	    name: ip_address
	    type: string
	    required: true
	    description: IP address to check
	    example: "192.168.1.100"
	responses:
	  200:
	    description: Blacklist check result
	    schema:
	      type: object
	      properties:
	        ip_address:
	          type: string
	        is_blacklisted:
	          type: boolean
	        entry:
	          type: object
	          properties:
	            id:
	              type: integer
	            reason:
	              type: string
	            source:
	              type: string
	            expires_at:
	              type: string
	              format: date-time
	            hit_count:
	              type: integer
	        message:
	          type: string
	  401:
	    description: Unauthorized
	"""
	conn = get_db_connection()
	cursor = conn.cursor()
	
	# Check if IP is blacklisted (and not expired)
	cursor.execute('''
		SELECT id, ip_address::text, reason, source, expires_at, hit_count, created_at
		FROM ip_blacklist
		WHERE ip_address = %s::inet
		AND (expires_at IS NULL OR expires_at > %s)
	''', (ip_address, datetime.now(timezone.utc)))
	
	result = cursor.fetchone()
	cursor.close()
	conn.close()
	
	if result:
		return jsonify({
			'ip_address': ip_address,
			'is_blacklisted': True,
			'entry': {
				'id': result['id'],
				'reason': result['reason'],
				'source': result['source'],
				'expires_at': result['expires_at'].isoformat() if result['expires_at'] else None,
				'hit_count': result['hit_count'],
				'ip_address': normalize_ip(result['ip_address'])
			},
			'message': f'IP {ip_address} is blacklisted'
		})
	else:
		return jsonify({
			'ip_address': ip_address,
			'is_blacklisted': False,
			'entry': None,
			'message': f'IP {ip_address} is not blacklisted'
		})


@bp.route('/api/blacklist/stats', methods=['GET'])
@token_required
def get_blacklist_stats():
	"""
	Get blacklist statistics
	---
	tags:
	  - Blacklist
	security:
	  - Bearer: []
	responses:
	  200:
	    description: Blacklist statistics
	    schema:
	      type: object
	      properties:
	        total_entries:
	          type: integer
	        active_entries:
	          type: integer
	        expired_entries:
	          type: integer
	        by_source:
	          type: object
	        top_hit_ips:
	          type: array
	          items:
	            type: object
	  401:
	    description: Unauthorized
	"""
	conn = get_db_connection()
	cursor = conn.cursor()
	
	# Total entries
	cursor.execute('SELECT COUNT(*) as count FROM ip_blacklist')
	total = cursor.fetchone()['count']
	
	# Active entries (not expired)
	cursor.execute('''
		SELECT COUNT(*) as count 
		FROM ip_blacklist 
		WHERE expires_at IS NULL OR expires_at > %s
	''', (datetime.now(timezone.utc),))
	active = cursor.fetchone()['count']
	
	# Expired entries
	cursor.execute('''
		SELECT COUNT(*) as count 
		FROM ip_blacklist 
		WHERE expires_at IS NOT NULL AND expires_at <= %s
	''', (datetime.now(timezone.utc),))
	expired = cursor.fetchone()['count']
	
	# By source
	cursor.execute('''
		SELECT source, COUNT(*) as count
		FROM ip_blacklist
		GROUP BY source
	''')
	by_source = {row['source']: row['count'] for row in cursor.fetchall()}
	
	# Top hit IPs
	cursor.execute('''
		SELECT ip_address::text, hit_count, reason
		FROM ip_blacklist
		ORDER BY hit_count DESC
		LIMIT 10
	''')
	top_hits = []
	for row in cursor.fetchall():
		entry = dict(row)
		entry['ip_address'] = normalize_ip(entry['ip_address'])
		top_hits.append(entry)
	
	cursor.close()
	conn.close()
	
	return jsonify({
		'total_entries': total,
		'active_entries': active,
		'expired_entries': expired,
		'by_source': by_source,
		'top_hit_ips': top_hits
	})
