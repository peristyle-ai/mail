"""
SPF (Sender Policy Framework) Validator

Validates that the sending IP is authorized to send email for the sender's domain.
Uses pyspf for full RFC 7208 compliance, with a simplified fallback.
"""

import logging
import ipaddress
import dns.resolver
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

# Try to import pyspf for full RFC 7208 compliance.
# Fall back to the simplified implementation if not available.
try:
	import spf as _pyspf
	_HAS_PYSPF = True
	logger.info("pyspf available — using full RFC 7208 SPF validation")
except ImportError:
	_HAS_PYSPF = False
	logger.info("pyspf not available — using simplified SPF validation")


class SPFValidator:
    """
    SPF validator for SMTP server.
    
    Checks if the sending IP is authorized to send email for the sender's domain
    by querying DNS SPF records.
    
    Uses pyspf (RFC 7208 compliant) when available, otherwise falls back to a
    simplified mechanism parser.
    
    Note: SPF validation is bypassed for localhost and internal/private IP addresses
    since SPF is meant to protect against external spoofing, not internal testing.
    """
    
    def __init__(self, reject_on_fail: bool = True):
        self.reject_on_fail = reject_on_fail
        logger.info(f"SPF validator initialized (reject_on_fail={reject_on_fail}, pyspf={_HAS_PYSPF})")
    
    def _is_internal_ip(self, ip: str) -> bool:
        """
        Check if IP is localhost or internal/private (not subject to SPF validation).
        
        Args:
            ip: IP address to check
            
        Returns:
            True if IP is localhost or internal
        """
        try:
            ip_obj = ipaddress.ip_address(ip)
            
            # Check for localhost
            if ip_obj.is_loopback:
                return True
            
            # Check for private networks
            if ip_obj.is_private:
                return True
            
            # Check for link-local
            if ip_obj.is_link_local:
                return True
                
            return False
        except ValueError:
            # Invalid IP, treat as internal to be safe
            logger.warning(f"Invalid IP address: {ip}, treating as internal")
            return True
    
    def validate(self, sender_ip: str, sender_email: str) -> Tuple[str, Optional[str]]:
        """
        Validate SPF for a sender.
        
        Args:
            sender_ip: IP address of the sender
            sender_email: Email address of the sender
            
        Returns:
            (result, explanation) where result is one of:
            - 'pass': SPF check passed
            - 'fail': SPF check failed (email rejected if reject_on_fail=True)
            - 'softfail': SPF check failed but not enforced
            - 'neutral': No strong SPF policy
            - 'none': No SPF record found
            - 'temperror': Temporary error (retry later)
            - 'permerror': Permanent error (bad SPF record)
        """
        try:
            # Skip SPF validation for localhost and internal IPs
            if self._is_internal_ip(sender_ip):
                logger.debug(f"SPF bypassed for internal IP: {sender_ip}")
                return 'pass', 'SPF bypassed for internal/localhost connection'
            
            # Extract domain from email
            domain = sender_email.split('@')[-1] if '@' in sender_email else sender_email
            
            # Use pyspf for full RFC 7208 compliance when available
            if _HAS_PYSPF:
                return self._validate_pyspf(sender_ip, sender_email, domain)
            
            # Fallback to simplified implementation
            return self._validate_simplified(sender_ip, sender_email, domain)
            
        except dns.resolver.NXDOMAIN:
            return 'none', 'Domain does not exist'
        except dns.resolver.NoAnswer:
            return 'none', 'No SPF record found'
        except Exception as e:
            logger.error(f"SPF validation error: {e}")
            return 'temperror', f'SPF validation error: {str(e)}'
    
    def _validate_pyspf(self, sender_ip: str, sender_email: str, domain: str) -> Tuple[str, Optional[str]]:
        """Validate SPF using pyspf (full RFC 7208 compliance)."""
        try:
            result, explanation = _pyspf.check2(sender_ip, sender_email, domain)
            
            # Map pyspf results to our result format
            if result == 'pass':
                logger.info(f"SPF pass: {sender_email} from {sender_ip}")
                return 'pass', explanation
            elif result == 'fail':
                if self.reject_on_fail:
                    logger.warning(f"SPF fail (rejected): {sender_email} from {sender_ip}: {explanation}")
                    return 'fail', f'SPF validation failed: {explanation}'
                else:
                    logger.warning(f"SPF fail (flagged): {sender_email} from {sender_ip}: {explanation}")
                    return 'softfail', f'SPF validation failed but not enforced: {explanation}'
            elif result == 'softfail':
                logger.info(f"SPF softfail: {sender_email} from {sender_ip}: {explanation}")
                return 'softfail', explanation
            elif result == 'neutral':
                return 'neutral', explanation
            elif result == 'none':
                return 'none', explanation
            elif result == 'temperror':
                return 'temperror', explanation
            elif result == 'permerror':
                return 'permerror', explanation
            else:
                return result, explanation
                
        except Exception as e:
            logger.error(f"pyspf validation error: {e}")
            return 'temperror', f'SPF validation error: {str(e)}'
    
    def _validate_simplified(self, sender_ip: str, sender_email: str, domain: str) -> Tuple[str, Optional[str]]:
        """Fallback simplified SPF validation (original implementation)."""
        # Query SPF record
        spf_record = self._get_spf_record(domain)
        
        if not spf_record:
            logger.debug(f"No SPF record for {domain}")
            return 'none', 'No SPF record found'
        
        # Simple SPF check (mechanism parsing would need more code)
        result = self._check_spf_mechanisms(spf_record, sender_ip, domain)
        
        if result == 'pass':
            logger.info(f"SPF pass: {sender_email} from {sender_ip}")
            return 'pass', 'SPF validation passed'
        elif result == 'fail':
            if self.reject_on_fail:
                logger.warning(f"SPF fail (rejected): {sender_email} from {sender_ip}")
                return 'fail', 'SPF validation failed - sender not authorized'
            else:
                logger.warning(f"SPF fail (flagged): {sender_email} from {sender_ip}")
                return 'softfail', 'SPF validation failed but not enforced'
        else:
            return result, f'SPF result: {result}'
    
    def _get_spf_record(self, domain: str) -> Optional[str]:
        """Query DNS for SPF record."""
        try:
            answers = dns.resolver.resolve(domain, 'TXT')
            for rdata in answers:
                for txt_string in rdata.strings:
                    txt = txt_string.decode('utf-8') if isinstance(txt_string, bytes) else txt_string
                    if txt.startswith('v=spf1'):
                        return txt
            return None
        except Exception as e:
            logger.debug(f"DNS query failed for {domain}: {e}")
            return None
    
    def _check_spf_mechanisms(self, spf_record: str, sender_ip: str, domain: str) -> str:
        """
        Check SPF mechanisms against sender IP.
        
        This is a simplified implementation. Full SPF parsing is complex.
        """
        mechanisms = spf_record.split()
        
        # Check for common mechanisms
        for mech in mechanisms:
            if mech.startswith('ip4:'):
                # Check IPv4 match
                ip_range = mech[4:]
                if self._ip_in_range(sender_ip, ip_range):
                    return 'pass'
            elif mech.startswith('ip6:'):
                # IPv6 check (simplified)
                if mech[4:] == sender_ip:
                    return 'pass'
            elif mech == 'a':
                # A record check
                if self._ip_matches_a_record(sender_ip, domain):
                    return 'pass'
            elif mech == 'mx':
                # MX record check
                if self._ip_matches_mx_record(sender_ip, domain):
                    return 'pass'
            elif mech.startswith('include:'):
                # Include another domain's SPF
                include_domain = mech[8:]
                include_spf = self._get_spf_record(include_domain)
                if include_spf:
                    result = self._check_spf_mechanisms(include_spf, sender_ip, include_domain)
                    if result == 'pass':
                        return 'pass'
            elif mech == 'all':
                # Default result
                return 'fail'
            elif mech == '-all':
                # Hard fail
                return 'fail'
            elif mech == '~all':
                # Soft fail
                return 'softfail'
            elif mech == '?all':
                # Neutral
                return 'neutral'
        
        return 'neutral'
    
    def _ip_in_range(self, ip: str, ip_range: str) -> bool:
        """Check if IP is in CIDR range (simplified)."""
        import ipaddress
        try:
            if '/' in ip_range:
                network = ipaddress.ip_network(ip_range, strict=False)
                return ipaddress.ip_address(ip) in network
            else:
                return ip == ip_range
        except:
            return False
    
    def _ip_matches_a_record(self, ip: str, domain: str) -> bool:
        """Check if IP matches A record for domain."""
        try:
            answers = dns.resolver.resolve(domain, 'A')
            for rdata in answers:
                if str(rdata) == ip:
                    return True
            return False
        except:
            return False
    
    def _ip_matches_mx_record(self, ip: str, domain: str) -> bool:
        """Check if IP matches MX records for domain."""
        try:
            answers = dns.resolver.resolve(domain, 'MX')
            for rdata in answers:
                mx_domain = str(rdata.exchange).rstrip('.')
                if self._ip_matches_a_record(ip, mx_domain):
                    return True
            return False
        except:
            return False
