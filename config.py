"""
Configuration loader for the mail server.

Loads settings from config.yaml with environment variable overrides.
"""

import os
import yaml
from pathlib import Path
from typing import Any, Dict, Optional

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    PROJECT_ROOT = Path(__file__).parent
    ENV_FILE = PROJECT_ROOT / '.env'
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE)
except ImportError:
    pass  # python-dotenv not installed, env vars must be set manually

# Project root directory - this file is in the project root
PROJECT_ROOT = Path(__file__).parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / 'config.yaml'


class MailServerConfig:
    """
    Mail server configuration manager.
    
    Loads settings from config.yaml and allows environment variable overrides.
    All paths in config are relative to PROJECT_ROOT.
    """
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize configuration.
        
        Args:
            config_path: Path to config YAML file. If None, uses default.
        """
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self._config: Dict[str, Any] = {}
        self._load_config()
    
    def _load_config(self):
        """Load configuration from YAML file."""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r') as f:
                    self._config = yaml.safe_load(f) or {}
            except Exception as e:
                print(f"Warning: Could not load config from {self.config_path}: {e}")
                self._config = {}
        else:
            print(f"Warning: Config file not found at {self.config_path}, using defaults")
            self._config = {}
    
    def _get_nested(self, *keys: str, default: Any = None) -> Any:
        """
        Get nested config value.
        
        Args:
            *keys: Nested keys to traverse
            default: Default value if not found
            
        Returns:
            Config value or default
        """
        value = self._config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value
    
    def _resolve_path(self, path: str) -> str:
        """
        Resolve relative path to absolute path from PROJECT_ROOT.
        
        Args:
            path: Path string, may be relative or absolute
            
        Returns:
            Absolute path string
        """
        if path.startswith('/') or path.startswith('~'):
            return os.path.expanduser(path)
        return str(PROJECT_ROOT / path)
    
    # SMTP Server Settings
    @property
    def smtp_host(self) -> str:
        """SMTP server bind address."""
        return os.getenv('SMTP_HOST', self._get_nested('smtp', 'host', default='0.0.0.0'))
    
    @property
    def smtp_port(self) -> int:
        """SMTP server port."""
        return int(os.getenv('SMTP_PORT', self._get_nested('smtp', 'port', default=2525)))
    
    @property
    def smtp_hostname(self) -> str:
        """
        SMTP EHLO/HELO hostname.
        
        This is crucial for reverse DNS (PTR) validation.
        Should match your reverse DNS record.
        Uses DOMAIN env var if SMTP_HOSTNAME not set.
        """
        hostname = os.getenv('SMTP_HOSTNAME')
        if hostname:
            return hostname
        
        # Fall back to DOMAIN env var
        domain = self.domain
        if domain and domain != 'localhost':
            return domain
        
        return self._get_nested('smtp', 'hostname', default='localhost')
    
    @property
    def smtp_debug(self) -> bool:
        """Enable SMTP debug logging."""
        env_val = os.getenv('SMTP_DEBUG')
        if env_val is not None:
            return env_val.lower() == 'true'
        return self._get_nested('smtp', 'debug', default=False)
    
    @property
    def smtp_enable_smtputf8(self) -> bool:
        """Enable SMTP UTF-8 support."""
        return self._get_nested('smtp', 'enable_smtputf8', default=True)
    
    # Outbound Settings
    @property
    def outbound_server_host(self) -> str:
        """Outbound SMTP server host for sending emails."""
        return os.getenv('OUTBOUND_SMTP_HOST', 
                        self._get_nested('outbound', 'server_host', default='127.0.0.1'))
    
    @property
    def outbound_server_port(self) -> int:
        """Outbound SMTP server port."""
        return int(os.getenv('OUTBOUND_SMTP_PORT', 
                              self._get_nested('outbound', 'server_port', default=2525)))
    
    @property
    def outbound_default_from(self) -> str:
        """
        Default from address for outbound emails.
        
        Uses OUTBOUND_DEFAULT_FROM env var, or constructs from DOMAIN.
        """
        from_addr = os.getenv('OUTBOUND_DEFAULT_FROM')
        if from_addr:
            return from_addr
        
        # Fall back to DOMAIN env var
        domain = self.domain
        if domain and domain != 'localhost':
            return f"noreply@{domain}"
        
        return self._get_nested('outbound', 'default_from', default='noreply@localhost')
    
    @property
    def outbound_reply_to(self) -> str:
        """Reply-to address for outbound emails."""
        reply_to = os.getenv('OUTBOUND_REPLY_TO')
        if reply_to:
            return reply_to
        
        # If not set, construct from domain
        domain = self.domain
        if domain and domain != 'localhost':
            return f"admin@{domain}"
        return self._get_nested('outbound', 'reply_to', default='')
    
    # Domain Settings
    @property
    def domain(self) -> str:
        """
        Domain name for this mail server.
        
        Used for constructing email addresses and reverse DNS validation.
        """
        return os.getenv('DOMAIN', 'localhost')
    
    @property
    def static_ip(self) -> str:
        """
        Static public IP address of this server.
        
        Used for reverse DNS (PTR) validation and SPF records.
        """
        return os.getenv('STATIC_IP', '')
    
    @property
    def local_test_email(self) -> str:
        """
        Local test email address for internal testing.
        
        Should be an address on your domain.
        """
        return os.getenv('LOCAL_TEST_EMAIL', f"test@{self.domain}")
    
    @property
    def external_test_email(self) -> str:
        """
        External test email address for outbound delivery testing.
        
        Should be an external address like Gmail for testing delivery.
        """
        return os.getenv('EXTERNAL_TEST_EMAIL', 'external-test@example.com')
    
    # Security Settings
    @property
    def security_rate_limit_enabled(self) -> bool:
        """Enable rate limiting."""
        env_val = os.getenv('SMTP_RATE_LIMIT_ENABLED')
        if env_val is not None:
            return env_val.lower() == 'true'
        return self._get_nested('security', 'rate_limit', 'enabled', default=True)
    
    @property
    def security_rate_limit_max_connections(self) -> int:
        """Maximum concurrent connections per IP."""
        return int(os.getenv('SMTP_RATE_LIMIT_MAX_CONNECTIONS',
                            self._get_nested('security', 'rate_limit', 'max_connections', default=10)))
    
    @property
    def security_rate_limit_max_emails_per_minute(self) -> int:
        """Maximum emails per minute per IP."""
        return int(os.getenv('SMTP_RATE_LIMIT_MAX_EMAILS_PER_MINUTE',
                            self._get_nested('security', 'rate_limit', 'max_emails_per_minute', default=30)))
    
    @property
    def security_rate_limit_max_emails_per_hour(self) -> int:
        """Maximum emails per hour per IP."""
        return int(os.getenv('SMTP_RATE_LIMIT_MAX_EMAILS_PER_HOUR',
                            self._get_nested('security', 'rate_limit', 'max_emails_per_hour', default=100)))
    
    @property
    def security_spf_enabled(self) -> bool:
        """Enable SPF validation."""
        env_val = os.getenv('SMTP_SPF_ENABLED')
        if env_val is not None:
            return env_val.lower() == 'true'
        return self._get_nested('security', 'spf', 'enabled', default=True)
    
    @property
    def security_spf_reject_on_fail(self) -> bool:
        """Reject emails that fail SPF validation."""
        env_val = os.getenv('SMTP_SPF_REJECT_FAIL')
        if env_val is not None:
            return env_val.lower() == 'true'
        return self._get_nested('security', 'spf', 'reject_on_fail', default=True)
    
    @property
    def security_greylist_enabled(self) -> bool:
        """Enable greylisting."""
        env_val = os.getenv('SMTP_GREYLIST_ENABLED')
        if env_val is not None:
            return env_val.lower() == 'true'
        return self._get_nested('security', 'greylist', 'enabled', default=True)
    
    @property
    def security_greylist_delay_minutes(self) -> int:
        """Greylist delay in minutes."""
        return int(os.getenv('SMTP_GREYLIST_DELAY_MINUTES',
                            self._get_nested('security', 'greylist', 'delay_minutes', default=5)))
    
    @property
    def security_greylist_whitelist_days(self) -> int:
        """Greylist whitelist duration in days."""
        return int(os.getenv('SMTP_GREYLIST_WHITELIST_DAYS',
                            self._get_nested('security', 'greylist', 'whitelist_days', default=30)))
    
    @property
    def security_tls_enabled(self) -> bool:
        """Enable TLS/SSL."""
        env_val = os.getenv('SMTP_TLS_ENABLED')
        if env_val is not None:
            return env_val.lower() == 'true'
        return self._get_nested('security', 'tls', 'enabled', default=True)
    
    @property
    def security_tls_force(self) -> bool:
        """Force TLS for all connections."""
        env_val = os.getenv('SMTP_TLS_FORCE')
        if env_val is not None:
            return env_val.lower() == 'true'
        return self._get_nested('security', 'tls', 'force', default=False)
    
    @property
    def security_tls_cert_path(self) -> str:
        """Path to TLS certificate."""
        path = os.getenv('SMTP_TLS_CERT_PATH',
                        self._get_nested('security', 'tls', 'cert_path', default='certs/server.crt'))
        return self._resolve_path(path)
    
    @property
    def security_tls_key_path(self) -> str:
        """Path to TLS private key."""
        path = os.getenv('SMTP_TLS_KEY_PATH',
                        self._resolve_path(self._get_nested('security', 'tls', 'key_path', default='certs/server.key')))
        return path
    
    # API Settings
    @property
    def api_host(self) -> str:
        """API server bind address."""
        return os.getenv('API_HOST', self._get_nested('api', 'host', default='0.0.0.0'))
    
    @property
    def api_port(self) -> int:
        """API server port."""
        return int(os.getenv('API_PORT', self._get_nested('api', 'port', default=5000)))
    
    @property
    def api_debug(self) -> bool:
        """Enable API debug mode."""
        env_val = os.getenv('API_DEBUG')
        if env_val is not None:
            return env_val.lower() == 'true'
        return self._get_nested('api', 'debug', default=False)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            'domain': self.domain,
            'static_ip': self.static_ip,
            'local_test_email': self.local_test_email,
            'external_test_email': self.external_test_email,
            'smtp': {
                'host': self.smtp_host,
                'port': self.smtp_port,
                'hostname': self.smtp_hostname,
                'debug': self.smtp_debug,
                'enable_smtputf8': self.smtp_enable_smtputf8,
            },
            'outbound': {
                'server_host': self.outbound_server_host,
                'server_port': self.outbound_server_port,
                'default_from': self.outbound_default_from,
                'reply_to': self.outbound_reply_to,
            },
            'security': {
                'rate_limit': {
                    'enabled': self.security_rate_limit_enabled,
                    'max_connections': self.security_rate_limit_max_connections,
                    'max_emails_per_minute': self.security_rate_limit_max_emails_per_minute,
                    'max_emails_per_hour': self.security_rate_limit_max_emails_per_hour,
                },
                'spf': {
                    'enabled': self.security_spf_enabled,
                    'reject_on_fail': self.security_spf_reject_on_fail,
                },
                'greylist': {
                    'enabled': self.security_greylist_enabled,
                    'delay_minutes': self.security_greylist_delay_minutes,
                    'whitelist_days': self.security_greylist_whitelist_days,
                },
                'tls': {
                    'enabled': self.security_tls_enabled,
                    'force': self.security_tls_force,
                    'cert_path': self.security_tls_cert_path,
                    'key_path': self.security_tls_key_path,
                },
            },
            'api': {
                'host': self.api_host,
                'port': self.api_port,
                'debug': self.api_debug,
            },
        }
    
    def __str__(self) -> str:
        """Return string representation of configuration."""
        lines = [
            "Mail Server Configuration:",
            "",
            f"Domain Settings:",
            f"  Domain: {self.domain}",
            f"  Static IP: {self.static_ip or '(not set)'}",
            f"  Local Test: {self.local_test_email}",
            f"  External Test: {self.external_test_email}",
            "",
            f"SMTP Server:",
            f"  Host: {self.smtp_host}:{self.smtp_port}",
            f"  EHLO/HELO Hostname: {self.smtp_hostname}",
            f"  Debug: {self.smtp_debug}",
            "",
            f"Outbound Mail:",
            f"  Server: {self.outbound_server_host}:{self.outbound_server_port}",
            f"  Default From: {self.outbound_default_from}",
            f"  Reply-To: {self.outbound_reply_to or '(not set)'}",
            "",
            f"Security:",
            f"  Rate Limit: {self.security_rate_limit_enabled} (conn: {self.security_rate_limit_max_connections}, "
            f"min: {self.security_rate_limit_max_emails_per_minute}, hour: {self.security_rate_limit_max_emails_per_hour})",
            f"  SPF: {self.security_spf_enabled} (reject: {self.security_spf_reject_on_fail})",
            f"  Greylist: {self.security_greylist_enabled} (delay: {self.security_greylist_delay_minutes}m, "
            f"whitelist: {self.security_greylist_whitelist_days}d)",
            f"  TLS: {self.security_tls_enabled} (force: {self.security_tls_force})",
            f"    Cert: {self.security_tls_cert_path}",
            f"    Key: {self.security_tls_key_path}",
            "",
            f"API Server:",
            f"  Host: {self.api_host}:{self.api_port}",
            f"  Debug: {self.api_debug}",
        ]
        return '\n'.join(lines)


# Global configuration instance
mail_config = MailServerConfig()


def get_config(config_path: Optional[str] = None) -> MailServerConfig:
    """
    Get configuration instance.
    
    Args:
        config_path: Optional path to config file
        
    Returns:
        MailServerConfig instance
    """
    if config_path:
        return MailServerConfig(config_path)
    return mail_config
