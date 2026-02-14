"""
SMTP Server Security Module

Provides security features for the SMTP server:
- Rate limiting to prevent abuse
- SPF validation to prevent spoofing
- Greylisting to reduce spam
- TLS/SSL encryption for secure connections
"""

import os
import sys
from pathlib import Path
from typing import Optional

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from config import get_config
    _config_available = True
except ImportError:
    _config_available = False


class SecurityConfig:
    """Configuration for SMTP security features."""
    
    def __init__(self):
        # Try to load from config.yaml if available
        config_loaded = False
        if _config_available:
            try:
                from config import get_config as _get_config
                config = _get_config()
                self._load_from_config(config)
                config_loaded = True
            except Exception:
                pass
        
        if not config_loaded:
            self._load_from_env()
    
    def _load_from_config(self, config):
        """Load settings from config.yaml via config module."""
        # Rate limiting settings
        self.rate_limit_enabled = config.security_rate_limit_enabled
        self.rate_limit_max_connections = config.security_rate_limit_max_connections
        self.rate_limit_max_emails_per_minute = config.security_rate_limit_max_emails_per_minute
        self.rate_limit_max_emails_per_hour = config.security_rate_limit_max_emails_per_hour
        
        # SPF settings
        self.spf_enabled = config.security_spf_enabled
        self.spf_reject_fail = config.security_spf_reject_on_fail
        
        # Greylisting settings
        self.greylist_enabled = config.security_greylist_enabled
        self.greylist_delay_minutes = config.security_greylist_delay_minutes
        self.greylist_whitelist_days = config.security_greylist_whitelist_days
        
        # TLS settings
        self.tls_enabled = config.security_tls_enabled
        self.tls_cert_path = config.security_tls_cert_path
        self.tls_key_path = config.security_tls_key_path
        self.tls_force = config.security_tls_force
    
    def _load_from_env(self):
        """Load settings from environment variables (fallback)."""
        # Rate limiting settings
        self.rate_limit_enabled = os.getenv('SMTP_RATE_LIMIT_ENABLED', 'true').lower() == 'true'
        self.rate_limit_max_connections = int(os.getenv('SMTP_RATE_LIMIT_MAX_CONNECTIONS', '10'))
        self.rate_limit_max_emails_per_minute = int(os.getenv('SMTP_RATE_LIMIT_MAX_EMAILS_PER_MINUTE', '30'))
        self.rate_limit_max_emails_per_hour = int(os.getenv('SMTP_RATE_LIMIT_MAX_EMAILS_PER_HOUR', '100'))
        
        # SPF settings
        self.spf_enabled = os.getenv('SMTP_SPF_ENABLED', 'true').lower() == 'true'
        self.spf_reject_fail = os.getenv('SMTP_SPF_REJECT_FAIL', 'true').lower() == 'true'
        
        # Greylisting settings
        self.greylist_enabled = os.getenv('SMTP_GREYLIST_ENABLED', 'true').lower() == 'true'
        self.greylist_delay_minutes = int(os.getenv('SMTP_GREYLIST_DELAY_MINUTES', '5'))
        self.greylist_whitelist_days = int(os.getenv('SMTP_GREYLIST_WHITELIST_DAYS', '30'))
        
        # TLS settings - use PROJECT_ROOT for default paths
        project_root = Path(__file__).parent.parent.parent
        self.tls_enabled = os.getenv('SMTP_TLS_ENABLED', 'true').lower() == 'true'
        default_cert = str(project_root / 'certs' / 'server.crt')
        default_key = str(project_root / 'certs' / 'server.key')
        self.tls_cert_path = os.getenv('SMTP_TLS_CERT_PATH', default_cert)
        self.tls_key_path = os.getenv('SMTP_TLS_KEY_PATH', default_key)
        self.tls_force = os.getenv('SMTP_TLS_FORCE', 'false').lower() == 'true'
    
    def __str__(self):
        """Return configuration summary."""
        return (
            f"SecurityConfig:\n"
            f"  Rate Limit: {'enabled' if self.rate_limit_enabled else 'disabled'}\n"
            f"    - Max connections: {self.rate_limit_max_connections}\n"
            f"    - Max emails/min: {self.rate_limit_max_emails_per_minute}\n"
            f"    - Max emails/hour: {self.rate_limit_max_emails_per_hour}\n"
            f"  SPF: {'enabled' if self.spf_enabled else 'disabled'}\n"
            f"    - Reject on fail: {self.spf_reject_fail}\n"
            f"  Greylisting: {'enabled' if self.greylist_enabled else 'disabled'}\n"
            f"    - Delay: {self.greylist_delay_minutes} minutes\n"
            f"    - Whitelist duration: {self.greylist_whitelist_days} days\n"
            f"  TLS: {'enabled' if self.tls_enabled else 'disabled'}\n"
            f"    - Force TLS: {self.tls_force}\n"
            f"    - Cert: {self.tls_cert_path}\n"
            f"    - Key: {self.tls_key_path}"
        )


# Global configuration instance
security_config = SecurityConfig()

from .rate_limiter import RateLimiter
from .spf_validator import SPFValidator
from .greylist import GreylistManager
from .tls_config import TLSConfig

__all__ = [
    'SecurityConfig',
    'security_config',
    'RateLimiter',
    'SPFValidator',
    'GreylistManager',
    'TLSConfig'
]
