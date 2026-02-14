#!/usr/bin/env python3
"""
Display current mail server configuration.

Usage:
    python scripts/show_config.py
    
This script displays the current configuration loaded from config.yaml
and environment variables, helping you verify your setup.
"""

import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import get_config, PROJECT_ROOT


def main():
	"""Display current mail server configuration."""
	config = get_config()
	
	print("="*70)
	print("MAIL SERVER CONFIGURATION")
	print("="*70)
	print()
	print(f"Project Root: {PROJECT_ROOT}")
	print()
	
	# SMTP Configuration
	print("SMTP Server:")
	print(f"  Bind Address: {config.smtp_host}:{config.smtp_port}")
	print(f"  EHLO/HELO Hostname: {config.smtp_hostname}")
	print(f"  UTF-8 Support: {config.smtp_enable_smtputf8}")
	print(f"  Debug Mode: {config.smtp_debug}")
	print()
	
	# Outbound Configuration
	print("Outbound Mail:")
	print(f"  SMTP Server: {config.outbound_server_host}:{config.outbound_server_port}")
	print(f"  Default From: {config.outbound_default_from}")
	print(f"  Reply-To: {config.outbound_reply_to or '(not set)'}")
	print()
	
	# Security Configuration
	print("Security Settings:")
	print(f"  Rate Limiting: {'Enabled' if config.security_rate_limit_enabled else 'Disabled'}")
	if config.security_rate_limit_enabled:
		print(f"    - Max Connections: {config.security_rate_limit_max_connections}")
		print(f"    - Max Emails/Minute: {config.security_rate_limit_max_emails_per_minute}")
		print(f"    - Max Emails/Hour: {config.security_rate_limit_max_emails_per_hour}")
	
	print(f"  SPF Validation: {'Enabled' if config.security_spf_enabled else 'Disabled'}")
	if config.security_spf_enabled:
		print(f"    - Reject on Fail: {config.security_spf_reject_on_fail}")
	
	print(f"  Greylisting: {'Enabled' if config.security_greylist_enabled else 'Disabled'}")
	if config.security_greylist_enabled:
		print(f"    - Delay: {config.security_greylist_delay_minutes} minutes")
		print(f"    - Whitelist Duration: {config.security_greylist_whitelist_days} days")
	
	print(f"  TLS/SSL: {'Enabled' if config.security_tls_enabled else 'Disabled'}")
	if config.security_tls_enabled:
		print(f"    - Force TLS: {config.security_tls_force}")
		print(f"    - Certificate: {config.security_tls_cert_path}")
		print(f"    - Private Key: {config.security_tls_key_path}")
	print()
	
	# API Configuration
	print("API Server:")
	print(f"  Bind Address: {config.api_host}:{config.api_port}")
	print(f"  Debug Mode: {config.api_debug}")
	print()
	
	# Configuration File Info
	config_path = PROJECT_ROOT / 'config.yaml'
	print("="*70)
	print("CONFIGURATION SOURCE")
	print("="*70)
	print()
	if config_path.exists():
		print(f"✓ Config file found: {config_path}")
		print()
		print("Values shown above are from config.yaml")
		print("(Environment variables can override these values)")
	else:
		print(f"✗ Config file NOT found: {config_path}")
		print()
		print("Using default values only")
	print()
	
	# Recommendations for Reverse DNS
	print("="*70)
	print("REVERSE DNS CHECKLIST")
	print("="*70)
	print()
	print("To verify your reverse DNS is configured correctly:")
	print()
	print("1. Your static IP should have a PTR record pointing to:")
	print(f"   {config.smtp_hostname}")
	print()
	print("2. Your domain DNS should have:")
	print(f"   A Record: {config.smtp_hostname} → <your-static-ip>")
	print(f"   MX Record: {config.domain} → {config.smtp_hostname}")
	print()
	print("3. Run the reverse DNS test:")
	print("   python scripts/test_reverse_dns.py")
	print()
	print("4. Check that the Received header shows your hostname, not just IP")
	print()


if __name__ == '__main__':
	main()
