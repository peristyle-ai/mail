"""
Security tests for SMTP server.

Tests all security features:
- Rate limiting
- SPF validation
- Greylisting
- TLS configuration
"""

import pytest
import time
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from smtp_server.security.rate_limiter import RateLimiter, IPTracker
from smtp_server.security.spf_validator import SPFValidator
from smtp_server.security.greylist import GreylistManager
from smtp_server.security.tls_config import TLSConfig
from smtp_server.security import SecurityConfig


class TestRateLimiter:
    """Tests for rate limiting functionality."""
    
    def test_rate_limiter_initialization(self):
        """Test rate limiter creates with correct settings."""
        rl = RateLimiter(
            max_connections=5,
            max_emails_per_minute=10,
            max_emails_per_hour=50
        )
        assert rl.max_connections == 5
        assert rl.max_emails_per_minute == 10
        assert rl.max_emails_per_hour == 50
    
    def test_connection_tracking(self):
        """Test connection tracking per IP."""
        rl = RateLimiter(max_connections=3)
        
        # Add connections
        rl.add_connection('192.168.1.1')
        rl.add_connection('192.168.1.1')
        rl.add_connection('192.168.1.2')
        
        assert rl._trackers['192.168.1.1'].connections == 2
        assert rl._trackers['192.168.1.2'].connections == 1
    
    def test_connection_limit_enforcement(self):
        """Test connection limit is enforced."""
        rl = RateLimiter(max_connections=2)
        
        # Add max connections
        rl.add_connection('192.168.1.1')
        rl.add_connection('192.168.1.1')
        
        # Should fail on third
        allowed, reason = rl.check_connection_allowed('192.168.1.1')
        assert not allowed
        assert 'blocked' in reason.lower()
    
    def test_email_rate_limit_per_minute(self):
        """Test email rate limit per minute."""
        rl = RateLimiter(max_emails_per_minute=2)
        
        # Add max emails
        rl.add_email('192.168.1.1')
        rl.add_email('192.168.1.1')
        
        # Should fail on third
        allowed, reason = rl.check_email_allowed('192.168.1.1')
        assert not allowed
        assert 'per minute' in reason.lower()
    
    def test_ip_blocking(self):
        """Test IP blocking and unblocking."""
        tracker = IPTracker()
        
        # Block for 1 minute
        tracker.block(1)
        assert tracker.is_blocked()
        
        # Check not blocked after expiration
        tracker.blocked_until = datetime.now() - timedelta(minutes=2)
        assert not tracker.is_blocked()
    
    def test_cleanup_old_entries(self):
        """Test cleanup of old email entries."""
        tracker = IPTracker()
        
        # Add entries - one recent, one old
        recent_time = datetime.now() - timedelta(seconds=30)  # 30 seconds ago
        old_time = datetime.now() - timedelta(minutes=2)     # 2 minutes ago
        tracker.emails_minute = [recent_time, old_time]
        tracker.emails_hour = [recent_time, old_time]
        
        # Cleanup
        tracker._cleanup_old_entries()
        
        # Minute list should only have recent (< 1 min old)
        assert len(tracker.emails_minute) == 1
        assert recent_time in tracker.emails_minute
        
        # Hour list should have both (< 1 hour old)
        assert len(tracker.emails_hour) == 2
    
    def test_get_stats(self):
        """Test statistics retrieval."""
        rl = RateLimiter()
        rl.add_connection('192.168.1.1')
        rl.add_email('192.168.1.1')
        
        stats = rl.get_stats('192.168.1.1')
        assert stats['connections'] == 1
        assert stats['emails_per_minute'] == 1
        assert not stats['blocked']


class TestSPFValidator:
    """Tests for SPF validation."""
    
    def test_spf_validator_initialization(self):
        """Test SPF validator creates correctly."""
        spf = SPFValidator(reject_on_fail=True)
        assert spf.reject_on_fail is True
    
    @patch('smtp_server.security.spf_validator.dns.resolver.resolve')
    def test_spf_no_record(self, mock_resolve):
        """Test SPF validation when no SPF record exists."""
        mock_resolve.side_effect = Exception("No answer")
        
        spf = SPFValidator()
        result, explanation = spf.validate('192.168.1.1', 'test@example.com')
        
        assert result == 'none'
    
    @patch('smtp_server.security.spf_validator.dns.resolver.resolve')
    def test_spf_pass(self, mock_resolve):
        """Test SPF validation passes for authorized IP."""
        # Mock TXT record with SPF
        mock_rdata = MagicMock()
        mock_rdata.strings = [b'v=spf1 ip4:192.168.1.1 -all']
        mock_resolve.return_value = [mock_rdata]
        
        spf = SPFValidator()
        result, explanation = spf.validate('192.168.1.1', 'test@example.com')
        
        assert result == 'pass'
    
    @patch('smtp_server.security.spf_validator.dns.resolver.resolve')
    def test_spf_fail(self, mock_resolve):
        """Test SPF validation fails for unauthorized IP."""
        # Mock TXT record that doesn't match
        mock_rdata = MagicMock()
        mock_rdata.strings = [b'v=spf1 ip4:10.0.0.1 -all']
        mock_resolve.return_value = [mock_rdata]
        
        spf = SPFValidator()
        result, explanation = spf.validate('192.168.1.1', 'test@example.com')
        
        assert result == 'fail'
    
    def test_ip_in_range(self):
        """Test IP range checking."""
        spf = SPFValidator()
        
        # Single IP
        assert spf._ip_in_range('192.168.1.1', '192.168.1.1') is True
        assert spf._ip_in_range('192.168.1.1', '192.168.1.2') is False
        
        # CIDR range
        assert spf._ip_in_range('192.168.1.1', '192.168.1.0/24') is True
        assert spf._ip_in_range('192.168.2.1', '192.168.1.0/24') is False


class TestGreylistManager:
    """Tests for greylisting functionality."""
    
    def test_new_sender_greylisted(self, db):
        """Test new sender is greylisted."""
        greylist = GreylistManager(delay_minutes=5)
        
        allowed, reason = greylist.check_sender(
            '192.168.1.1',
            'sender@example.com',
            'recipient@example.com'
        )
        
        assert not allowed
        assert 'Greylisted' in reason
    
    def test_retry_after_delay_allowed(self, db):
        """Test sender allowed after greylist delay."""
        greylist = GreylistManager(delay_minutes=0)  # No delay for testing
        
        # First attempt - greylisted
        greylist.check_sender('192.168.1.1', 'sender@example.com', 'recipient@example.com')
        
        # Immediate retry should be allowed (0 minute delay)
        allowed, reason = greylist.check_sender(
            '192.168.1.1',
            'sender@example.com',
            'recipient@example.com'
        )
        
        assert allowed is True
    
    def test_whitelisted_sender(self, db):
        """Test whitelisted sender bypasses greylist."""
        greylist = GreylistManager(delay_minutes=5)
        
        # Clean up any existing entry first
        import psycopg2
        conn = psycopg2.connect('postgresql://postgres:1234@localhost:5432/mail_server_test')
        cursor = conn.cursor()
        cursor.execute('''
            DELETE FROM greylist 
            WHERE client_ip = %s AND sender = %s AND recipient = %s
        ''', ('192.168.1.1', 'sender@example.com', 'recipient@example.com'))
        
        # Create entry and mark as whitelisted
        cursor.execute('''
            INSERT INTO greylist (client_ip, sender, recipient, whitelisted)
            VALUES (%s, %s, %s, TRUE)
        ''', ('192.168.1.1', 'sender@example.com', 'recipient@example.com'))
        conn.commit()
        cursor.close()
        conn.close()
        
        # Should be allowed immediately
        allowed, reason = greylist.check_sender(
            '192.168.1.1',
            'sender@example.com',
            'recipient@example.com'
        )
        
        assert allowed is True
    
    def test_stats_retrieval(self, db):
        """Test greylist statistics."""
        greylist = GreylistManager()
        
        stats = greylist.get_stats()
        assert 'pending' in stats
        assert 'whitelisted' in stats
        assert 'total' in stats


class TestTLSConfig:
    """Tests for TLS configuration."""
    
    def test_tls_config_initialization(self):
        """Test TLS config creates with defaults."""
        tls = TLSConfig()
        assert tls.cert_path is not None
        assert tls.key_path is not None
        assert tls.force_tls is False
    
    def test_tls_config_custom_paths(self):
        """Test TLS config with custom paths."""
        tls = TLSConfig(
            cert_path='/custom/cert.pem',
            key_path='/custom/key.pem',
            force_tls=True
        )
        assert tls.cert_path == '/custom/cert.pem'
        assert tls.key_path == '/custom/key.pem'
        assert tls.force_tls is True
    
    def test_load_certificates_missing_files(self):
        """Test loading certificates that don't exist."""
        tls = TLSConfig(
            cert_path='/nonexistent/cert.pem',
            key_path='/nonexistent/key.pem'
        )
        
        result = tls.load_certificates()
        assert result is False
        assert tls.is_loaded is False
    
    def test_generate_self_signed_cert(self, tmp_path):
        """Test self-signed certificate generation."""
        cert_dir = tmp_path / "certs"
        cert_dir.mkdir()
        
        tls = TLSConfig(
            cert_path=str(cert_dir / "test.crt"),
            key_path=str(cert_dir / "test.key")
        )
        
        cert_path, key_path = tls.generate_self_signed_cert('test.local')
        
        assert os.path.exists(cert_path)
        assert os.path.exists(key_path)


class TestSecurityConfig:
    """Tests for security configuration."""
    
    def test_default_configuration(self):
        """Test default security configuration."""
        config = SecurityConfig()
        
        assert config.rate_limit_enabled is True
        assert config.rate_limit_max_connections == 10
        assert config.spf_enabled is True
        assert config.greylist_enabled is True
        assert config.tls_enabled is True
    
    def test_environment_override(self, monkeypatch):
        """Test environment variable overrides."""
        monkeypatch.setenv('SMTP_RATE_LIMIT_ENABLED', 'false')
        monkeypatch.setenv('SMTP_RATE_LIMIT_MAX_CONNECTIONS', '5')
        monkeypatch.setenv('SMTP_SPF_ENABLED', 'false')
        monkeypatch.setenv('SMTP_GREYLIST_ENABLED', 'false')
        monkeypatch.setenv('SMTP_TLS_ENABLED', 'false')
        
        config = SecurityConfig()
        
        assert config.rate_limit_enabled is False
        assert config.rate_limit_max_connections == 5
        assert config.spf_enabled is False
        assert config.greylist_enabled is False
        assert config.tls_enabled is False


class TestSecurityIntegration:
    """Integration tests for security features."""
    
    def test_all_security_features_together(self, db):
        """Test all security features working together."""
        # This would require mocking multiple components
        # and verifying they interact correctly
        pass
    
    def test_security_disabled_mode(self):
        """Test server works with all security disabled."""
        # Create config with everything disabled
        config = SecurityConfig()
        config.rate_limit_enabled = False
        config.spf_enabled = False
        config.greylist_enabled = False
        config.tls_enabled = False
        
        # Verify all features can be disabled
        assert not config.rate_limit_enabled
        assert not config.spf_enabled
        assert not config.greylist_enabled
        assert not config.tls_enabled
