"""
MX Record Lookup Module

Queries DNS for MX records to find recipient mail servers.
"""

import dns.resolver
import dns.exception
import logging
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)


class MXLookup:
	"""MX record lookup for outbound email delivery."""
	
	def __init__(self, timeout: int = 10):
		self.timeout = timeout
	
	def get_mx_records(self, domain: str) -> List[Tuple[int, str]]:
		"""
		Get MX records for a domain, sorted by priority.
		
		Args:
			domain: Domain name to query
			
		Returns:
			List of (priority, mail_server) tuples, sorted by priority
		"""
		try:
			answers = dns.resolver.resolve(domain, 'MX', lifetime=self.timeout)
			records = []
			for rdata in answers:
				priority = rdata.preference
				server = str(rdata.exchange).rstrip('.')
				records.append((priority, server))
			
			# Sort by priority (lower is better)
			records.sort(key=lambda x: x[0])
			logger.debug(f"Found {len(records)} MX records for {domain}: {records}")
			return records
			
		except dns.resolver.NXDOMAIN:
			logger.warning(f"Domain {domain} does not exist (NXDOMAIN)")
			return []
		except dns.resolver.NoAnswer:
			logger.warning(f"No MX records found for {domain}")
			return []
		except dns.exception.Timeout:
			logger.error(f"DNS timeout looking up MX for {domain}")
			return []
		except Exception as e:
			logger.error(f"Error looking up MX for {domain}: {e}")
			return []
	
	def get_a_record(self, domain: str) -> Optional[str]:
		"""
		Get A record for a domain as fallback.
		
		Args:
			domain: Domain name to query
			
		Returns:
			IP address if found, None otherwise
		"""
		try:
			answers = dns.resolver.resolve(domain, 'A', lifetime=self.timeout)
			for rdata in answers:
				return str(rdata)
			return None
		except Exception as e:
			logger.debug(f"No A record for {domain}: {e}")
			return None
	
	def get_mail_server(self, email: str) -> Optional[Tuple[str, int]]:
		"""
		Get best mail server for an email address.
		
		Args:
			email: Email address
			
		Returns:
			Tuple of (server, port) or None if not found
			
		Strategy:
		1. Try MX records
		2. Fallback to A record (mail server on domain itself)
		3. Return None if neither works
		"""
		try:
			domain = email.split('@')[-1].lower().strip()
			if not domain:
				logger.warning(f"No domain found in email: {email}")
				return None
			
			# Try MX records first
			mx_records = self.get_mx_records(domain)
			if mx_records:
				# Return the best (lowest priority) mail server
				return (mx_records[0][1], 25)
			
			# Fallback to A record
			a_record = self.get_a_record(domain)
			if a_record:
				logger.info(f"Using A record fallback for {domain}: {a_record}")
				return (a_record, 25)
			
			logger.error(f"No mail server found for {domain}")
			return None
			
		except Exception as e:
			logger.error(f"Error getting mail server for {email}: {e}")
			return None
	
	def verify_domain_exists(self, domain: str) -> bool:
		"""Check if domain has any DNS records."""
		try:
			# Try MX records
			mx = self.get_mx_records(domain)
			if mx:
				return True
			
			# Try A record
			a = self.get_a_record(domain)
			if a:
				return True
			
			return False
		except:
			return False
