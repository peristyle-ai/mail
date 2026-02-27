"""
Sender Blocklist Checker

Checks if a sender email address or domain is blocked.
Used by SMTP handler to reject emails from blocked senders.
"""

import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import get_db_connection

logger = logging.getLogger(__name__)


def check_sender_blocked(sender_email: str) -> tuple:
	"""
	Check if sender is in the blocklist.
	
	Args:
		sender_email: Email address to check
		
	Returns:
		Tuple of (is_blocked, block_entry)
	"""
	if not sender_email:
		return False, None
	
	# Normalize sender email
	sender_email = sender_email.lower().strip('<>"\'')
	domain = sender_email.split('@')[-1] if '@' in sender_email else None
	
	if not domain:
		return False, None
	
	try:
		conn = get_db_connection()
		cursor = conn.cursor()
		
		# Check both specific email and domain block
		cursor.execute('''
			SELECT id, email, domain, source, notes, blocked_at
			FROM sender_blocklist
			WHERE email = %s OR (domain = %s AND email IS NULL)
			LIMIT 1
		''', (sender_email, domain))
		
		result = cursor.fetchone()
		cursor.close()
		conn.close()
		
		if result:
			return True, dict(result)
		return False, None
		
	except Exception as e:
		logger.error(f"Error checking sender blocklist: {e}")
		return False, None  # Allow on error
