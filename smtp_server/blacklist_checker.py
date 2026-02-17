"""
IP Blacklist Checker

Checks if an IP address is blacklisted and manages hit counts.
"""

import logging
from datetime import datetime, timezone
from typing import Tuple, Optional, Dict, Any
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import get_db_connection

logger = logging.getLogger(__name__)


def check_ip_blacklisted(ip_address: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
	"""
	Check if an IP address is blacklisted.
	
	Args:
		ip_address: IP address to check (IPv4 or IPv6)
		
	Returns:
		Tuple of (is_blacklisted, entry_details)
		If blacklisted, entry_details contains reason, source, etc.
		If not blacklisted, entry_details is None
	"""
	try:
		conn = get_db_connection()
		cursor = conn.cursor()
		
		# Check if IP is in blacklist and not expired
		cursor.execute('''
			SELECT id, ip_address::text, reason, source, expires_at, hit_count
			FROM ip_blacklist
			WHERE ip_address = %s::inet
			AND (expires_at IS NULL OR expires_at > %s)
		''', (ip_address, datetime.now(timezone.utc)))
		
		result = cursor.fetchone()
		cursor.close()
		conn.close()
		
		if result:
			return True, {
				'id': result['id'],
				'ip_address': result['ip_address'],
				'reason': result['reason'],
				'source': result['source'],
				'expires_at': result['expires_at'],
				'hit_count': result['hit_count']
			}
		else:
			return False, None
			
	except Exception as e:
		logger.error(f"Error checking blacklist for {ip_address}: {e}")
		# Fail open - don't block if there's a database error
		return False, None


def increment_blacklist_hit(ip_address: str) -> None:
	"""
	Increment the hit count for a blacklisted IP.
	
	Args:
		ip_address: IP address to increment hit count for
	"""
	try:
		conn = get_db_connection()
		cursor = conn.cursor()
		
		cursor.execute('''
			UPDATE ip_blacklist
			SET hit_count = hit_count + 1
			WHERE ip_address = %s::inet
		''', (ip_address,))
		
		conn.commit()
		cursor.close()
		conn.close()
		
	except Exception as e:
		logger.error(f"Error incrementing hit count for {ip_address}: {e}")


def cleanup_expired_blacklist_entries() -> int:
	"""
	Remove expired blacklist entries.
	
	Returns:
		Number of entries removed
	"""
	try:
		conn = get_db_connection()
		cursor = conn.cursor()
		
		cursor.execute('''
			DELETE FROM ip_blacklist
			WHERE expires_at IS NOT NULL
			AND expires_at <= %s
			RETURNING id
		''', (datetime.now(timezone.utc),))
		
		deleted = cursor.fetchall()
		conn.commit()
		cursor.close()
		conn.close()
		
		count = len(deleted)
		if count > 0:
			logger.info(f"Cleaned up {count} expired blacklist entries")
		return count
		
	except Exception as e:
		logger.error(f"Error cleaning up expired blacklist entries: {e}")
		return 0
