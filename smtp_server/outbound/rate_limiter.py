"""
Outbound Rate Limiter

Prevents abuse and IP blacklisting by limiting outbound emails.
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Tuple
from collections import defaultdict

logger = logging.getLogger(__name__)


class OutboundRateLimiter:
	"""Rate limiter for outbound email delivery."""
	
	def __init__(
		self,
		max_per_domain_per_minute: int = 30,
		max_per_hour: int = 100,
		max_concurrent_per_domain: int = 5
	):
		self.max_per_domain_per_minute = max_per_domain_per_minute
		self.max_per_hour = max_per_hour
		self.max_concurrent_per_domain = max_concurrent_per_domain
		
		# Tracking structures
		self.domain_timestamps: Dict[str, list] = defaultdict(list)
		self.hourly_count = 0
		self.hour_start = datetime.now()
		self.domain_connections: Dict[str, int] = defaultdict(int)
		
		logger.info(
			f"Outbound rate limiter: "
			f"{max_per_domain_per_minute}/min per domain, "
			f"{max_per_hour}/hour total"
		)
	
	def _cleanup_old_entries(self):
		"""Remove timestamps older than 1 minute."""
		now = datetime.now()
		cutoff = now - timedelta(minutes=1)
		
		for domain in self.domain_timestamps:
			self.domain_timestamps[domain] = [
				ts for ts in self.domain_timestamps[domain]
				if ts > cutoff
			]
		
		# Reset hourly count if needed
		if now - self.hour_start > timedelta(hours=1):
			self.hourly_count = 0
			self.hour_start = now
	
	def check_rate_limit(self, domain: str) -> Tuple[bool, str]:
		"""
		Check if sending to domain is allowed.
		
		Returns:
			Tuple of (allowed, message)
		"""
		self._cleanup_old_entries()
		
		# Check hourly global limit
		if self.hourly_count >= self.max_per_hour:
			return False, f"Hourly limit reached ({self.max_per_hour}/hour)"
		
		# Check domain per-minute limit
		domain_count = len(self.domain_timestamps.get(domain, []))
		if domain_count >= self.max_per_domain_per_minute:
			return False, f"Domain rate limit reached ({self.max_per_domain_per_minute}/min)"
		
		return True, "OK"
	
	def record_send(self, domain: str):
		"""Record that an email was sent."""
		now = datetime.now()
		self.domain_timestamps[domain].append(now)
		self.hourly_count += 1
		logger.debug(f"Recorded send to {domain}. Hourly: {self.hourly_count}")
	
	def check_concurrent(self, domain: str) -> bool:
		"""Check if can start concurrent connection to domain."""
		return self.domain_connections[domain] < self.max_concurrent_per_domain
	
	def start_connection(self, domain: str):
		"""Mark that we're starting a connection to domain."""
		self.domain_connections[domain] += 1
	
	def end_connection(self, domain: str):
		"""Mark that we've finished a connection to domain."""
		self.domain_connections[domain] = max(0, self.domain_connections[domain] - 1)
	
	def get_stats(self) -> Dict:
		"""Get current rate limiting stats."""
		self._cleanup_old_entries()
		return {
			'hourly_count': self.hourly_count,
			'hourly_limit': self.max_per_hour,
			'domain_counts': {
				domain: len(timestamps)
				for domain, timestamps in self.domain_timestamps.items()
			},
			'active_connections': dict(self.domain_connections)
		}
