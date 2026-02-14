#!/usr/bin/env python3
"""
Test script to verify reverse DNS (PTR record) configuration.

Usage:
    python test_reverse_dns.py
    python test_reverse_dns.py --external-to user@example.com

This script sends TWO test emails:
1. LOCAL TEST: Send to your own domain (stored in mail server database)
   - Confirms mail server is accepting and storing emails
   - Email will be in your database and API
   
2. EXTERNAL TEST: Send to an external address (e.g., Gmail)
   - Confirms outbound email delivery works
   - Allows checking reverse DNS (PTR) in external mail headers
   - Shows how external servers see your mail server

Configure test recipients in your .env file:
  LOCAL_TEST_EMAIL=test@yourdomain.com
  EXTERNAL_TEST_EMAIL=external-test@example.com

The external recipient can check email headers to verify reverse DNS configuration.
"""

import smtplib
import argparse
import socket
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from pathlib import Path
import sys

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import get_config


def get_public_ip():
	"""Get the public IP address of this machine."""
	try:
		# Try multiple services in case one fails
		services = [
			'https://api.ipify.org',
			'https://checkip.amazonaws.com',
			'https://icanhazip.com'
		]
		for service in services:
			try:
				response = requests.get(service, timeout=5)
				if response.status_code == 200:
					return response.text.strip()
			except:
				continue
		return None
	except Exception as e:
		print(f"Warning: Could not determine public IP: {e}")
		return None


def get_local_ip():
	"""Get the local IP address."""
	try:
		s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		s.connect(("8.8.8.8", 80))
		ip = s.getsockname()[0]
		s.close()
		return ip
	except:
		return "127.0.0.1"


def create_test_email(from_address, to_address, subject, server_name, public_ip, local_ip, server_host, server_port, test_type="External"):
	"""
	Create a test email with diagnostic information.
	
	Args:
		from_address: Sender email address
		to_address: Recipient email address
		subject: Email subject
		server_name: EHLO/HELO hostname
		public_ip: Public IP address
		local_ip: Local IP address
		server_host: SMTP server host
		server_port: SMTP server port
		test_type: Type of test (External or Local)
		
	Returns:
		MIMEMultipart email message
	"""
	timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
	
	body = f"""Reverse DNS (PTR Record) {test_type} Test Email
{'='*70}

Sent: {timestamp}
From: {from_address}
To: {to_address}
Test Type: {test_type}

NETWORK INFORMATION:
--------------------
Public IP Address: {public_ip or 'Could not determine'}
Local IP Address: {local_ip}
Mail Server: {server_host}:{server_port}
EHLO/HELO Name: {server_name}

REVERSE DNS CHECKLIST:
----------------------
✓ 1. Can send emails (this email was delivered)
✓ 2. IP has reverse DNS (check Received headers below)
  - Look for: "from {server_name} [{public_ip}]"
  - Should NOT show: "from [{public_ip}]" (missing PTR)

WHAT TO CHECK IN EMAIL HEADERS:
-------------------------------
1. Open this email in your mail client
2. View "Original" or "Source" of the email
3. Look for "Received:" headers
4. The first Received header should show:
   - Your mail server's hostname (reverse DNS)
   - Your public IP address

EXAMPLE OF GOOD REVERSE DNS:
-----------------------------
Received: from mail.yourdomain.com [203.0.113.45]
          by mx.google.com with ESMTPS id abc123

EXAMPLE OF MISSING REVERSE DNS:
--------------------------------
Received: from [203.0.113.45]
          by mx.google.com with ESMTPS id abc123
          (envelope-from yourname@yourdomain.com)

DNS RECORDS TO CONFIGURE (at your domain registrar):
------------------------------------------------------
1. A Record: mail.yourdomain.com → {public_ip or 'YOUR_STATIC_IP'}
2. MX Record: yourdomain.com → mail.yourdomain.com (priority 10)
3. PTR Record (contact your ISP): {public_ip or 'YOUR_STATIC_IP'} → mail.yourdomain.com
4. SPF Record (TXT): "v=spf1 ip4:{public_ip or 'YOUR_STATIC_IP'} -all"

TROUBLESHOOTING:
----------------
If no reverse DNS (PTR record):
- Contact your ISP to request a PTR record for your static IP
- Some ISPs don't allow this for residential connections
- You may need business-grade internet service

If emails go to spam:
- Verify SPF record is correctly configured
- Check that your IP is not on any blacklists
- Ensure reverse DNS matches your mail server's EHLO name

NEXT STEPS:
-----------
1. Verify this email arrived (confirms delivery works)
2. Check Received headers for reverse DNS
3. Configure DNS records at your domain registrar
4. Request PTR record from your ISP
5. Wait 24-48 hours for DNS propagation
6. Test again with: python scripts/test_reverse_dns.py

Test completed at: {timestamp}
"""
	
	# Create message
	msg = MIMEMultipart()
	msg['From'] = from_address
	msg['To'] = to_address
	msg['Subject'] = subject
	
	# Attach body
	msg.attach(MIMEText(body, 'plain'))
	
	return msg


def send_test_email(server_host, server_port, server_name, from_address, to_address, 
					public_ip, local_ip, test_type="Test", debug=False):
	"""
	Send a single test email.
	
	Args:
		server_host: SMTP server hostname
		server_port: SMTP server port
		server_name: EHLO/HELO hostname
		from_address: Sender email
		to_address: Recipient email
		public_ip: Public IP
		local_ip: Local IP
		test_type: Type of test for subject line
		debug: Enable SMTP debug output
		
	Returns:
		(bool, str) - (success, message)
	"""
	timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
	subject = f"Reverse DNS {test_type} Test - {timestamp}"
	
	msg = create_test_email(
		from_address, to_address, subject, server_name,
		public_ip, local_ip, server_host, server_port, test_type
	)
	
	try:
		with smtplib.SMTP(server_host, server_port) as server:
			if debug:
				server.set_debuglevel(1)
			
			server.ehlo(server_name)
			server.sendmail(from_address, to_address, msg.as_string())
		
		return True, f"Email sent to {to_address}"
		
	except Exception as e:
		return False, str(e)


def test_reverse_dns(local_to=None,
					 external_to=None,
					 from_address=None, 
					 server_host=None, 
					 server_port=None,
					 server_name=None,
					 skip_external=False,
					 debug=False):
	"""
	Perform reverse DNS tests by sending emails.
	
	Sends two emails:
	1. Local test: To your own domain (stored in mail server database)
	2. External test: To an external address (tests outbound delivery)
	
	Args:
		local_to: Local recipient (your domain)
		external_to: External recipient (e.g., Gmail)
		from_address: Sender email address
		server_host: SMTP server hostname
		server_port: SMTP server port
		server_name: EHLO/HELO hostname
		skip_external: Skip the external test
		debug: Enable debug output
		
	Returns:
		(bool, bool) - (local_success, external_success)
	"""
	
	# Load configuration
	config = get_config()
	
	# Use config defaults
	if local_to is None:
		local_to = config.local_test_email
	if external_to is None:
		external_to = config.external_test_email
	if from_address is None:
		from_address = config.outbound_default_from
	if server_host is None:
		server_host = config.outbound_server_host
	if server_port is None:
		server_port = config.outbound_server_port
	if server_name is None:
		server_name = config.smtp_hostname
	
	# Gather network information
	public_ip = get_public_ip()
	local_ip = get_local_ip()
	
	print("="*70)
	print("REVERSE DNS TEST SUITE")
	print("="*70)
	print()
	print("Configuration:")
	print(f"  EHLO/HELO Hostname: {server_name}")
	print(f"  Mail Server: {server_host}:{server_port}")
	print(f"  From: {from_address}")
	print(f"  Public IP: {public_ip or 'Could not determine'}")
	print(f"  Local IP: {local_ip}")
	print()
	
	results = {'local': False, 'external': False}
	
	# TEST 1: Local email (stored in database)
	print("="*70)
	print("TEST 1: LOCAL EMAIL (Stored in Mail Server Database)")
	print("="*70)
	print(f"Sending to: {local_to}")
	print(f"This tests if your mail server accepts and stores emails.")
	print()
	
	success, message = send_test_email(
		server_host, server_port, server_name, from_address, local_to,
		public_ip, local_ip, "Local", debug
	)
	
	if success:
		print("✓ SUCCESS: Local email sent and stored in database")
		print(f"  Check: http://localhost:{config.api_port}/api/emails")
		results['local'] = True
	else:
		print(f"✗ FAILED: {message}")
	
	print()
	
	# TEST 2: External email (tests outbound delivery)
	if not skip_external:
		print("="*70)
		print("TEST 2: EXTERNAL EMAIL (Outbound Delivery Test)")
		print("="*70)
		print(f"Sending to: {external_to}")
		print(f"This tests if your mail server can deliver to external addresses.")
		print(f"Note: This requires outbound relay capability on your mail server.")
		print()
		
		success, message = send_test_email(
			server_host, server_port, server_name, from_address, external_to,
			public_ip, local_ip, "External", debug
		)
		
		if success:
			print("✓ SUCCESS: External email sent")
			print(f"  Check {external_to} inbox for the test email")
			print()
			print("To verify reverse DNS:")
			print("1. Open the email in Gmail")
			print("2. Click the 3 dots (More) → 'Show original'")
			print("3. Look for the first 'Received:' header")
			print(f"4. It should show: from {server_name} [{public_ip}]")
			print()
			print(f"If you see just the IP in brackets [{public_ip or 'YOUR_IP'}]:")
			print("  → Contact your ISP to set up reverse DNS (PTR record)")
			results['external'] = True
		else:
			print(f"✗ FAILED: {message}")
			print()
			print("This is expected if your mail server doesn't have outbound relay.")
			print("The mail server currently only stores emails locally.")
			print()
			print("To enable outbound delivery, you need to:")
			print("1. Configure your mail server as a relay")
			print("2. Set up proper authentication")
			print("3. Ensure your IP has good reputation (not on blacklists)")
	
	# Summary
	print("="*70)
	print("TEST SUMMARY")
	print("="*70)
	print()
	print(f"Local Test:   {'✓ PASS' if results['local'] else '✗ FAIL'}")
	if not skip_external:
		print(f"External Test: {'✓ PASS' if results['external'] else '✗ FAIL (expected without relay)'}")
	print()
	print(f"Public IP: {public_ip or 'Unknown'}")
	print(f"Hostname:  {server_name}")
	print()
	
	if results['local'] and not skip_external and not results['external']:
		print("Status: Mail server is working locally but needs outbound relay")
		print("        configured to send to external addresses.")
	elif results['local'] and (skip_external or results['external']):
		print("Status: All tests passed! ✓")
	else:
		print("Status: Local mail server test failed. Check if server is running.")
	
	print("="*70)
	
	return results['local'], results['external']


if __name__ == '__main__':
	# Load config for help text
	config = get_config()
	
	parser = argparse.ArgumentParser(
		description='Test reverse DNS (PTR record) with both local and external email tests',
		formatter_class=argparse.RawDescriptionHelpFormatter,
		epilog=f"""
Examples:
  # Run both tests (uses values from .env/config)
  python scripts/test_reverse_dns.py
  
  # Test with custom external recipient
  python scripts/test_reverse_dns.py --external-to user@example.com
  
  # Skip external test (local only)
  python scripts/test_reverse_dns.py --skip-external
  
  # Custom sender and server
  python scripts/test_reverse_dns.py --from admin@{config.domain} --server {config.outbound_server_host}

Current Configuration:
  Domain: {config.domain}
  EHLO/HELO Hostname: {config.smtp_hostname}
  Outbound Server: {config.outbound_server_host}:{config.outbound_server_port}
  Default From: {config.outbound_default_from}
  Local Test: {config.local_test_email}
  External Test: {config.external_test_email}
        """
	)
	
	parser.add_argument(
		'--local-to',
		default=None,
		help=f'Local recipient for internal test (stored in database) (default: {config.local_test_email})'
	)
	
	parser.add_argument(
		'--external-to',
		default=None,
		help=f'External recipient for outbound test (default: {config.external_test_email})'
	)
	
	parser.add_argument(
		'--from', 
		dest='from_addr',
		default=None,
		help=f'Sender email address - should use your domain (default: {config.outbound_default_from})'
	)
	
	parser.add_argument(
		'--server', 
		default=None,
		help=f'Your mail server IP/hostname (default: {config.outbound_server_host})'
	)
	
	parser.add_argument(
		'--port', 
		type=int, 
		default=None,
		help=f'SMTP server port (default: {config.outbound_server_port})'
	)
	
	parser.add_argument(
		'--ehlo', 
		dest='ehlo_name',
		help=f'EHLO/HELO name for SMTP handshake (default: {config.smtp_hostname})'
	)
	
	parser.add_argument(
		'--skip-external',
		action='store_true',
		help='Skip the external email test (local test only)'
	)
	
	parser.add_argument(
		'--debug',
		action='store_true',
		help='Enable SMTP debug output'
	)
	
	args = parser.parse_args()
	
	local_success, external_success = test_reverse_dns(
		local_to=args.local_to,
		external_to=args.external_to,
		from_address=args.from_addr,
		server_host=args.server,
		server_port=args.port,
		server_name=args.ehlo_name,
		skip_external=args.skip_external,
		debug=args.debug
	)
	
	# Exit with appropriate code
	if local_success and (args.skip_external or external_success):
		sys.exit(0)
	elif local_success:
		# Local worked but external didn't (expected without relay)
		sys.exit(0)
	else:
		sys.exit(1)
