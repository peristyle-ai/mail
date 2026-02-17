"""
Tests for IP Blacklist functionality
"""

import pytest
from datetime import datetime, timezone, timedelta


class TestBlacklistAPI:
	"""Test blacklist API endpoints"""
	
	def test_list_blacklisted_ips_empty(self, client, auth_headers, db):
		"""Test listing blacklist when empty"""
		response = client.get('/api/blacklist/ip', headers=auth_headers)
		assert response.status_code == 200
		
		data = response.get_json()
		assert data['blacklisted_ips'] == []
		assert data['total'] == 0
	
	def test_add_ip_to_blacklist(self, client, auth_headers, db):
		"""Test adding IP to blacklist"""
		response = client.post('/api/blacklist/ip',
			headers=auth_headers,
			json={
				'ip_address': '192.168.1.100',
				'reason': 'Test blacklist',
				'source': 'manual'
			}
		)
		assert response.status_code == 201
		
		data = response.get_json()
		assert data['ip_address'] == '192.168.1.100'
		assert data['reason'] == 'Test blacklist'
		assert data['source'] == 'manual'
		assert 'id' in data
	
	def test_add_ip_with_expiration(self, client, auth_headers, db):
		"""Test adding IP with expiration date"""
		expires = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
		
		response = client.post('/api/blacklist/ip',
			headers=auth_headers,
			json={
				'ip_address': '192.168.1.101',
				'reason': 'Temporary block',
				'source': 'manual',
				'expires_at': expires
			}
		)
		assert response.status_code == 201
		
		data = response.get_json()
		assert data['expires_at'] is not None
	
	def test_add_invalid_ip(self, client, auth_headers, db):
		"""Test adding invalid IP address"""
		response = client.post('/api/blacklist/ip',
			headers=auth_headers,
			json={
				'ip_address': 'not-an-ip',
				'reason': 'Test'
			}
		)
		assert response.status_code == 400
	
	def test_add_duplicate_ip_updates(self, client, auth_headers, db):
		"""Test that adding duplicate IP updates existing entry"""
		# Add first time
		client.post('/api/blacklist/ip',
			headers=auth_headers,
			json={
				'ip_address': '192.168.1.102',
				'reason': 'First reason'
			}
		)
		
		# Add second time with different reason
		response = client.post('/api/blacklist/ip',
			headers=auth_headers,
			json={
				'ip_address': '192.168.1.102',
				'reason': 'Updated reason'
			}
		)
		assert response.status_code == 201
		
		data = response.get_json()
		assert data['reason'] == 'Updated reason'
	
	def test_remove_blacklisted_ip(self, client, auth_headers, db):
		"""Test removing IP from blacklist by ID"""
		# Add IP first
		add_response = client.post('/api/blacklist/ip',
			headers=auth_headers,
			json={'ip_address': '192.168.1.103', 'reason': 'Test'}
		)
		entry_id = add_response.get_json()['id']
		
		# Remove it
		response = client.delete(f'/api/blacklist/ip/{entry_id}', headers=auth_headers)
		assert response.status_code == 200
		
		data = response.get_json()
		assert data['status'] == 'removed'
		assert data['ip_address'] == '192.168.1.103'
	
	def test_remove_by_ip_address(self, client, auth_headers, db):
		"""Test removing IP by address (convenience endpoint)"""
		# Add IP first
		client.post('/api/blacklist/ip',
			headers=auth_headers,
			json={'ip_address': '192.168.1.104', 'reason': 'Test'}
		)
		
		# Remove by address
		response = client.delete('/api/blacklist/ip/address/192.168.1.104', headers=auth_headers)
		assert response.status_code == 200
		
		data = response.get_json()
		assert data['status'] == 'removed'
	
	def test_check_ip_blacklisted(self, client, auth_headers, db):
		"""Test checking if IP is blacklisted"""
		# Add IP to blacklist
		client.post('/api/blacklist/ip',
			headers=auth_headers,
			json={'ip_address': '192.168.1.105', 'reason': 'Test'}
		)
		
		# Check that it IS blacklisted
		response = client.get('/api/blacklist/ip/check/192.168.1.105', headers=auth_headers)
		assert response.status_code == 200
		
		data = response.get_json()
		assert data['is_blacklisted'] is True
		assert data['ip_address'] == '192.168.1.105'
		assert 'entry' in data
	
	def test_check_ip_not_blacklisted(self, client, auth_headers, db):
		"""Test checking IP that is not blacklisted"""
		response = client.get('/api/blacklist/ip/check/192.168.1.200', headers=auth_headers)
		assert response.status_code == 200
		
		data = response.get_json()
		assert data['is_blacklisted'] is False
		assert data['entry'] is None
	
	def test_list_blacklist_with_entries(self, client, auth_headers, db):
		"""Test listing blacklist with entries"""
		# Add multiple IPs
		for i in range(5):
			client.post('/api/blacklist/ip',
				headers=auth_headers,
				json={'ip_address': f'192.168.1.{i}', 'reason': f'Test {i}'}
			)
		
		response = client.get('/api/blacklist/ip', headers=auth_headers)
		assert response.status_code == 200
		
		data = response.get_json()
		assert data['total'] == 5
		assert len(data['blacklisted_ips']) == 5
	
	def test_blacklist_pagination(self, client, auth_headers, db):
		"""Test blacklist pagination"""
		# Add 10 IPs
		for i in range(10):
			client.post('/api/blacklist/ip',
				headers=auth_headers,
				json={'ip_address': f'192.168.2.{i}', 'reason': f'Test {i}'}
			)
		
		# Get page 1 with limit 5
		response = client.get('/api/blacklist/ip?page=1&limit=5', headers=auth_headers)
		assert response.status_code == 200
		
		data = response.get_json()
		assert data['total'] == 10
		assert len(data['blacklisted_ips']) == 5
		assert data['page'] == 1
		assert data['limit'] == 5
	
	def test_blacklist_stats(self, client, auth_headers, db):
		"""Test blacklist statistics endpoint"""
		# Add some IPs
		client.post('/api/blacklist/ip',
			headers=auth_headers,
			json={'ip_address': '192.168.3.1', 'reason': 'Test 1', 'source': 'manual'}
		)
		client.post('/api/blacklist/ip',
			headers=auth_headers,
			json={'ip_address': '192.168.3.2', 'reason': 'Test 2', 'source': 'auto_spf_fail'}
		)
		
		response = client.get('/api/blacklist/stats', headers=auth_headers)
		assert response.status_code == 200
		
		data = response.get_json()
		assert data['total_entries'] == 2
		assert data['active_entries'] == 2
		assert 'by_source' in data
		assert 'manual' in data['by_source'] or 'auto_spf_fail' in data['by_source']
	
	def test_add_ipv6_to_blacklist(self, client, auth_headers, db):
		"""Test adding IPv6 address to blacklist"""
		response = client.post('/api/blacklist/ip',
			headers=auth_headers,
			json={
				'ip_address': '2001:db8::1',
				'reason': 'IPv6 test'
			}
		)
		assert response.status_code == 201
		
		data = response.get_json()
		assert data['ip_address'] == '2001:db8::1'
	
	def test_invalid_source(self, client, auth_headers, db):
		"""Test adding with invalid source"""
		response = client.post('/api/blacklist/ip',
			headers=auth_headers,
			json={
				'ip_address': '192.168.1.106',
				'source': 'invalid_source'
			}
		)
		assert response.status_code == 400
		assert 'error' in response.get_json()
	
	def test_remove_nonexistent_ip(self, client, auth_headers, db):
		"""Test removing non-existent IP"""
		response = client.delete('/api/blacklist/ip/address/192.168.99.99', headers=auth_headers)
		assert response.status_code == 404
	
	def test_blacklist_requires_auth(self, client, db):
		"""Test that blacklist endpoints require authentication"""
		# Test GET without auth
		response = client.get('/api/blacklist/ip')
		assert response.status_code == 401
		
		# Test POST without auth
		response = client.post('/api/blacklist/ip', json={'ip_address': '192.168.1.1'})
		assert response.status_code == 401


class TestBlacklistChecker:
	"""Test blacklist checker functions (used by SMTP handler)"""
	
	def test_check_ip_blacklisted_true(self, db):
		"""Test checking blacklisted IP returns True"""
		from smtp_server.blacklist_checker import check_ip_blacklisted
		
		conn = db()
		cursor = conn.cursor()
		cursor.execute('''
			INSERT INTO ip_blacklist (ip_address, reason, source)
			VALUES ('192.168.10.1'::inet, 'Test', 'manual')
		''')
		conn.commit()
		cursor.close()
		conn.close()
		
		is_blacklisted, entry = check_ip_blacklisted('192.168.10.1')
		assert is_blacklisted is True
		assert entry is not None
		assert entry['reason'] == 'Test'
	
	def test_check_ip_blacklisted_false(self, db):
		"""Test checking non-blacklisted IP returns False"""
		from smtp_server.blacklist_checker import check_ip_blacklisted
		
		is_blacklisted, entry = check_ip_blacklisted('192.168.10.2')
		assert is_blacklisted is False
		assert entry is None
	
	def test_check_expired_ip_not_blacklisted(self, db):
		"""Test that expired entries are not considered blacklisted"""
		from smtp_server.blacklist_checker import check_ip_blacklisted
		
		conn = db()
		cursor = conn.cursor()
		# Add expired entry
		cursor.execute('''
			INSERT INTO ip_blacklist (ip_address, reason, source, expires_at)
			VALUES ('192.168.10.3'::inet, 'Expired', 'manual', %s)
		''', (datetime.now(timezone.utc) - timedelta(hours=1),))
		conn.commit()
		cursor.close()
		conn.close()
		
		is_blacklisted, entry = check_ip_blacklisted('192.168.10.3')
		assert is_blacklisted is False
	
	def test_increment_hit_count(self, db):
		"""Test incrementing hit count"""
		from smtp_server.blacklist_checker import check_ip_blacklisted, increment_blacklist_hit
		
		conn = db()
		cursor = conn.cursor()
		cursor.execute('''
			INSERT INTO ip_blacklist (ip_address, reason, source, hit_count)
			VALUES ('192.168.10.4'::inet, 'Test', 'manual', 0)
		''')
		conn.commit()
		cursor.close()
		conn.close()
		
		# Check initial state
		is_blacklisted, entry = check_ip_blacklisted('192.168.10.4')
		assert entry['hit_count'] == 0
		
		# Increment hit count
		increment_blacklist_hit('192.168.10.4')
		
		# Check updated state
		is_blacklisted, entry = check_ip_blacklisted('192.168.10.4')
		assert entry['hit_count'] == 1
	
	def test_cleanup_expired_entries(self, db):
		"""Test cleaning up expired blacklist entries"""
		from smtp_server.blacklist_checker import cleanup_expired_blacklist_entries
		
		conn = db()
		cursor = conn.cursor()
		# Add expired entry
		cursor.execute('''
			INSERT INTO ip_blacklist (ip_address, reason, source, expires_at)
			VALUES ('192.168.10.5'::inet, 'Expired', 'manual', %s)
		''', (datetime.now(timezone.utc) - timedelta(hours=1),))
		conn.commit()
		cursor.close()
		conn.close()
		
		# Cleanup should remove 1 entry
		deleted = cleanup_expired_blacklist_entries()
		assert deleted == 1
