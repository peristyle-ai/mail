"""
Database-backed rate limiter.

Replaces in-memory rate limiting with PostgreSQL-backed tracking that
survives restarts and coordinates across multiple workers.

Uses the existing `rate_limit_violations` table for violation logging,
plus a new `rate_limit_attempts` table for tracking attempt timestamps.

Falls back to in-memory tracking if the database table doesn't exist
(e.g. insufficient privileges to create it).
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional

from ..db import get_db_connection

logger = logging.getLogger(__name__)

# In-memory fallback when DB table is unavailable
_memory_attempts: dict = {}
_memory_cleanup_interval = 300  # 5 minutes
_last_memory_cleanup = time.time()


def _ensure_table(cursor):
	"""Create the rate_limit_attempts table if it doesn't exist.
	
	Tolerates InsufficientPrivilege — the runtime role may not have DDL
	privileges. In that case, the table must have been created by a prior
	privileged session (e.g. init_db.py or a migration).
	"""
	try:
		cursor.execute('''
			CREATE TABLE IF NOT EXISTS rate_limit_attempts (
				id SERIAL PRIMARY KEY,
				key VARCHAR(500) NOT NULL,
				attempted_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
			)
		''')
		cursor.execute('''
			CREATE INDEX IF NOT EXISTS idx_rate_limit_attempts_key
			ON rate_limit_attempts(key)
		''')
		cursor.execute('''
			CREATE INDEX IF NOT EXISTS idx_rate_limit_attempts_time
			ON rate_limit_attempts(attempted_at)
		''')
	except Exception as e:
		# Tolerate permission errors — table may already exist
		logger.debug(f"rate_limit_attempts table creation skipped: {e}")


def _table_exists(cursor) -> bool:
	"""Check if the rate_limit_attempts table exists."""
	try:
		cursor.execute(
			"SELECT 1 FROM information_schema.tables "
			"WHERE table_schema = 'public' AND table_name = 'rate_limit_attempts'"
		)
		return cursor.fetchone() is not None
	except Exception:
		return False


def _prune_old_attempts(cursor, key: str, window_seconds: int):
	"""Remove attempts older than the window."""
	cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
	cursor.execute(
		'DELETE FROM rate_limit_attempts WHERE key = %s AND attempted_at < %s',
		(key, cutoff)
	)


def _memory_prune(key: str, window_seconds: int):
	"""Prune old entries from in-memory store."""
	global _last_memory_cleanup
	now = time.time()
	if now - _last_memory_cleanup > _memory_cleanup_interval:
		# Periodic cleanup of all keys
		cutoff = now - 3600  # Keep last hour
		for k in list(_memory_attempts.keys()):
			_memory_attempts[k] = [t for t in _memory_attempts[k] if t > cutoff]
			if not _memory_attempts[k]:
				del _memory_attempts[k]
		_last_memory_cleanup = now
	
	cutoff = now - window_seconds
	attempts = _memory_attempts.get(key, [])
	_memory_attempts[key] = [t for t in attempts if t > cutoff]


def check_rate_limit(key: str, max_attempts: int, window_seconds: int) -> Tuple[bool, Optional[str]]:
	"""
	Check if an action is allowed under the rate limit.
	
	Args:
		key: Unique identifier (e.g. 'ip:192.168.1.1', 'combo:ip:email')
		max_attempts: Maximum attempts allowed in the window
		window_seconds: Time window in seconds
		
	Returns:
		(allowed, reason) — allowed is True if OK, False if rate limited
	"""
	conn = get_db_connection()
	cursor = conn.cursor()
	try:
		if not _table_exists(cursor):
			return _memory_check_rate_limit(key, max_attempts, window_seconds)
		
		_prune_old_attempts(cursor, key, window_seconds)
		
		cursor.execute(
			'SELECT COUNT(*) AS n FROM rate_limit_attempts WHERE key = %s',
			(key,)
		)
		count = cursor.fetchone()['n']
		
		if count >= max_attempts:
			# Log the violation
			try:
				cursor.execute(
					'''INSERT INTO rate_limit_violations (client_ip, violation_type, count)
					   VALUES (%s, %s, %s)''',
					(key.split(':')[1] if ':' in key else key, 'rate_limit_exceeded', count)
				)
			except Exception:
				pass  # Violations table may not exist either
			conn.commit()
			return False, f'Rate limit exceeded: {max_attempts} attempts per {window_seconds}s'
		
		conn.commit()
		return True, None
	except Exception as e:
		logger.debug(f"check_rate_limit DB error, using memory fallback: {e}")
		return _memory_check_rate_limit(key, max_attempts, window_seconds)
	finally:
		cursor.close()
		conn.close()


def _memory_check_rate_limit(key: str, max_attempts: int, window_seconds: int) -> Tuple[bool, Optional[str]]:
	"""In-memory fallback for rate limit checking."""
	_memory_prune(key, window_seconds)
	attempts = _memory_attempts.get(key, [])
	if len(attempts) >= max_attempts:
		return False, f'Rate limit exceeded: {max_attempts} attempts per {window_seconds}s'
	return True, None


def record_attempt(key: str):
	"""Record an attempt for rate limiting."""
	conn = get_db_connection()
	cursor = conn.cursor()
	try:
		if _table_exists(cursor):
			cursor.execute(
				'INSERT INTO rate_limit_attempts (key) VALUES (%s)',
				(key,)
			)
			conn.commit()
		else:
			_memory_attempts.setdefault(key, []).append(time.time())
	except Exception as e:
		logger.debug(f"record_attempt DB error, using memory fallback: {e}")
		_memory_attempts.setdefault(key, []).append(time.time())
	finally:
		cursor.close()
		conn.close()


def clear_attempts(key: str):
	"""Clear all attempts for a key (e.g. after successful login)."""
	conn = get_db_connection()
	cursor = conn.cursor()
	try:
		if _table_exists(cursor):
			cursor.execute(
				'DELETE FROM rate_limit_attempts WHERE key = %s',
				(key,)
			)
			conn.commit()
		else:
			_memory_attempts.pop(key, None)
	except Exception as e:
		logger.debug(f"clear_attempts DB error, using memory fallback: {e}")
		_memory_attempts.pop(key, None)
	finally:
		cursor.close()
		conn.close()


def cleanup_old_entries(max_age_hours: int = 24):
	"""Remove old entries to prevent table bloat."""
	conn = get_db_connection()
	cursor = conn.cursor()
	try:
		if _table_exists(cursor):
			cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
			cursor.execute(
				'DELETE FROM rate_limit_attempts WHERE attempted_at < %s',
				(cutoff,)
			)
			removed = cursor.rowcount
			conn.commit()
			if removed > 0:
				logger.info(f"Rate limiter cleanup: removed {removed} old entries")
			return removed
		else:
			# In-memory cleanup
			global _last_memory_cleanup
			now = time.time()
			cutoff = now - (max_age_hours * 3600)
			removed = 0
			for k in list(_memory_attempts.keys()):
				before = len(_memory_attempts[k])
				_memory_attempts[k] = [t for t in _memory_attempts[k] if t > cutoff]
				removed += before - len(_memory_attempts[k])
				if not _memory_attempts[k]:
					del _memory_attempts[k]
			_last_memory_cleanup = now
			if removed > 0:
				logger.info(f"Rate limiter memory cleanup: removed {removed} old entries")
			return removed
	finally:
		cursor.close()
		conn.close()
