#!/usr/bin/env python3
"""
Test script to send emails to the SMTP server.

Usage:
    python send_test_email.py --to test@yourdomain.com --server 127.0.0.1

This script sends a test email via SMTP to your local mail server.
Configure recipient in .env: LOCAL_TEST_EMAIL=test@yourdomain.com
"""

import smtplib
import argparse
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime
import io
from pathlib import Path
import sys

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import get_config


def create_test_attachment(filename="test_attachment.txt"):
    """Create a small test attachment."""
    content = f"""This is a test attachment.
Created at: {datetime.now().isoformat()}
Filename: {filename}

This file was attached to test the mail server's attachment handling.
"""
    return filename, content.encode('utf-8'), 'text/plain'


def send_test_email(to_address=None, server_host=None, server_port=2525, 
                    from_address=None, subject=None, body=None, 
                    attachment_filename=None, attachment_content=None, attachment_type=None):
    """
    Send a test email via SMTP.
    
    Args:
        to_address: Recipient email address
        server_host: SMTP server hostname/IP
        server_port: SMTP server port
        from_address: Sender email address
        subject: Email subject
        body: Email body
    """
    
    # Load configuration for defaults
    config = get_config()
    
    # Set defaults from config if not provided
    if to_address is None:
        to_address = config.local_test_email
    if server_host is None:
        server_host = config.outbound_server_host
    if from_address is None:
        from_address = f"test@{config.domain}" if config.domain != 'localhost' else 'test@example.com'
    
    # Default subject and body if not provided
    if subject is None:
        subject = f"Test Email from {from_address}"
    
    if body is None:
        body = f"""
This is a test email sent at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

If you can see this in your mail server's API, the SMTP reception is working!

Test Details:
- From: {from_address}
- To: {to_address}
- Server: {server_host}:{server_port}
- Sent: {datetime.now().isoformat()}

Best regards,
Test Script
"""
    
    # Create message
    msg = MIMEMultipart()
    msg['From'] = from_address
    msg['To'] = to_address
    msg['Subject'] = subject
    
    # Attach body
    msg.attach(MIMEText(body, 'plain'))
    
    # Attach file if provided
    if attachment_filename and attachment_content:
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(attachment_content)
        encoders.encode_base64(part)
        part.add_header(
            'Content-Disposition',
            f'attachment; filename= "{attachment_filename}"'
        )
        msg.attach(part)
        print(f"Attached file: {attachment_filename} ({len(attachment_content)} bytes)")
    
    try:
        print(f"Connecting to SMTP server at {server_host}:{server_port}...")
        
        # Connect to SMTP server
        with smtplib.SMTP(server_host, server_port) as server:
            server.set_debuglevel(1)  # Enable debug output
            
            print("Sending EHLO...")
            server.ehlo()
            
            print(f"Sending email from {from_address} to {to_address}...")
            server.sendmail(from_address, to_address, msg.as_string())
            
        print(f"\n✓ Email sent successfully!")
        print(f"  From: {from_address}")
        print(f"  To: {to_address}")
        print(f"  Subject: {subject}")
        if attachment_filename and attachment_content:
            print(f"  Attachment: {attachment_filename} ({len(attachment_content)} bytes)")
        print(f"\nCheck your mail server's API to verify the email was received.")
        return True
        
    except Exception as e:
        print(f"\n✗ Error sending email: {e}")
        print(f"\nTroubleshooting:")
        print(f"1. Is the SMTP server running on {server_host}:{server_port}?")
        print(f"2. Check firewall settings - port {server_port} must be open")
        print(f"3. Verify the mail server is accepting connections")
        return False


if __name__ == '__main__':
    # Load config for defaults
    config = get_config()
    
    parser = argparse.ArgumentParser(
        description='Send test email to local SMTP server',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
  # Send to default user (from .env config)
  python send_test_email.py
  
  # Send with custom subject and body
  python send_test_email.py --to user@example.com --subject "Hello" --body "Test message"
  
  # Send to localhost (same machine)
  python send_test_email.py --to test@localhost --server 127.0.0.1
  
  # Send with attachment
  python send_test_email.py --to user@example.com --attach

Current Configuration:
  Default Recipient: {config.local_test_email}
  Default Server: {config.outbound_server_host}:{config.outbound_server_port}
        """
    )
    
    parser.add_argument(
        '--to', 
        default=None,
        help=f'Recipient email address (default: {config.local_test_email})'
    )
    
    parser.add_argument(
        '--server', 
        default=None,
        help=f'SMTP server IP/hostname (default: {config.outbound_server_host})'
    )
    
    parser.add_argument(
        '--port', 
        type=int, 
        default=2525,
        help='SMTP server port (default: 2525, standard SMTP is 587 but requires root)'
    )
    
    parser.add_argument(
        '--from', 
        dest='from_addr',
        default=None,
        help=f'Sender email address (default: test@{config.domain})'
    )
    
    parser.add_argument(
        '--subject', 
        help='Email subject (default: auto-generated)'
    )
    
    parser.add_argument(
        '--body', 
        help='Email body text (default: auto-generated)'
    )
    
    parser.add_argument(
        '--attach', 
        action='store_true',
        help='Attach a test file to the email'
    )
    
    args = parser.parse_args()
    
    # Create attachment if requested
    attachment_filename = None
    attachment_content = None
    attachment_type = None
    if args.attach:
        attachment_filename, attachment_content, attachment_type = create_test_attachment()
    
    print("="*60)
    print("SMTP Test Email Sender")
    print("="*60)
    
    success = send_test_email(
        to_address=args.to,
        server_host=args.server,
        server_port=args.port,
        from_address=args.from_addr,
        subject=args.subject,
        body=args.body,
        attachment_filename=attachment_filename,
        attachment_content=attachment_content,
        attachment_type=attachment_type
    )
    
    if success:
        print("\n" + "="*60)
        print("Next steps:")
        print("1. Check your mail server's database/API")
        print("2. Visit http://localhost:5000/api/emails (with auth)")
        print("3. Or use Swagger UI at http://localhost:5000/docs")
        print("="*60)
