#!/usr/bin/env python3
"""
Test script to send emails to the SMTP server.

Usage:
    python send_test_email.py --to the operator@example.com.au --server 192.168.4.30

This script sends a test email via SMTP to your local mail server.
"""

import smtplib
import argparse
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime


def send_test_email(to_address, server_host='192.168.4.30', server_port=587, 
                    from_address='test@example.com', subject=None, body=None):
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
    parser = argparse.ArgumentParser(
        description='Send test email to local SMTP server',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Send to default user on local network
  python send_test_email.py --to the operator@example.com.au --server 192.168.4.30
  
  # Send with custom subject and body
  python send_test_email.py --to user@example.com --subject "Hello" --body "Test message"
  
  # Send to localhost (same machine)
  python send_test_email.py --to test@localhost --server 127.0.0.1
        """
    )
    
    parser.add_argument(
        '--to', 
        default='the operator@example.com.au',
        help='Recipient email address (default: the operator@example.com.au)'
    )
    
    parser.add_argument(
        '--server', 
        default='192.168.4.30',
        help='SMTP server IP/hostname (default: 192.168.4.30)'
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
        default='test@example.com',
        help='Sender email address (default: test@example.com)'
    )
    
    parser.add_argument(
        '--subject', 
        help='Email subject (default: auto-generated)'
    )
    
    parser.add_argument(
        '--body', 
        help='Email body text (default: auto-generated)'
    )
    
    args = parser.parse_args()
    
    print("="*60)
    print("SMTP Test Email Sender")
    print("="*60)
    
    success = send_test_email(
        to_address=args.to,
        server_host=args.server,
        server_port=args.port,
        from_address=args.from_addr,
        subject=args.subject,
        body=args.body
    )
    
    if success:
        print("\n" + "="*60)
        print("Next steps:")
        print("1. Check your mail server's database/API")
        print("2. Visit http://localhost:5000/api/emails (with auth)")
        print("3. Or use Swagger UI at http://localhost:5000/docs")
        print("="*60)
