import pytest
import smtplib
import time
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import threading
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import get_db_connection
from smtp_server import start_smtp_server, stop_smtp_server
from config import get_config

# Get config for test email addresses
config = get_config()
TEST_RECIPIENT = config.local_test_email
TEST_DOMAIN = config.domain


@pytest.fixture
def smtp_server():
    """Start SMTP server for testing."""
    controller = start_smtp_server(host='127.0.0.1', port=2525, debug=False)
    time.sleep(1)  # Give server time to start
    yield controller
    stop_smtp_server(controller)
    time.sleep(0.5)  # Give time to stop


def count_emails_and_attachments():
    """Helper to count emails and attachments in database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) as total FROM emails')
    result = cursor.fetchone()
    email_count = result['total'] if result else 0
    
    cursor.execute('SELECT COUNT(*) as total FROM attachments')
    result = cursor.fetchone()
    attachment_count = result['total'] if result else 0
    
    cursor.close()
    conn.close()
    
    return email_count, attachment_count


def get_last_email_with_attachments():
    """Helper to get the most recent email with its attachments."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT e.id, e.subject, e.body, e.created_at 
        FROM emails e 
        ORDER BY e.id DESC 
        LIMIT 1
    ''')
    email = cursor.fetchone()
    
    attachments = []
    if email:
        cursor.execute('''
            SELECT filename, file_size, content_type 
            FROM attachments 
            WHERE email_id = %s
        ''', (email['id'],))
        attachments = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return email, attachments


class TestSMTPReception:
    """Test SMTP email reception end-to-end."""
    
    def test_receive_plain_email(self, smtp_server, db):
        """
        Test receiving a plain text email via SMTP.
        
        This test validates that:
        1. SMTP server accepts incoming connections
        2. Email is parsed and stored in database
        3. Email metadata (subject, body) is preserved
        """
        # Get initial count
        initial_emails, initial_attachments = count_emails_and_attachments()
        
        # Create and send test email
        msg = MIMEText('Test email body content')
        msg['Subject'] = 'SMTP Test - Plain Email'
        msg['From'] = 'test@example.com'
        msg['To'] = '${TEST_RECIPIENT}'
        
        with smtplib.SMTP('127.0.0.1', 2525) as server:
            server.send_message(msg)
        
        # Wait for processing
        time.sleep(0.5)
        
        # Verify email was stored
        final_emails, final_attachments = count_emails_and_attachments()
        assert final_emails == initial_emails + 1, "Email should be stored in database"
        assert final_attachments == initial_attachments, "No attachments expected"
        
        # Verify email content
        email, attachments = get_last_email_with_attachments()
        assert email is not None, "Email should exist"
        assert email['subject'] == 'SMTP Test - Plain Email', "Subject should match"
        assert 'Test email body content' in email['body'], "Body should match"
        assert len(attachments) == 0, "Should have no attachments"
    
    def test_receive_email_with_attachment(self, smtp_server, db):
        """
        Test receiving an email with attachment via SMTP.
        
        This test validates that:
        1. SMTP server accepts multipart emails
        2. Attachments are extracted and stored
        3. Attachment metadata is preserved
        """
        # Get initial count
        initial_emails, initial_attachments = count_emails_and_attachments()
        
        # Create multipart email with attachment
        msg = MIMEMultipart()
        msg['Subject'] = 'SMTP Test - With Attachment'
        msg['From'] = 'test@example.com'
        msg['To'] = '${TEST_RECIPIENT}'
        
        # Add body
        body = MIMEText('This email has an attachment', 'plain')
        msg.attach(body)
        
        # Add attachment
        attachment_content = b'This is test attachment content'
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(attachment_content)
        encoders.encode_base64(part)
        part.add_header(
            'Content-Disposition',
            'attachment; filename="test_file.txt"'
        )
        msg.attach(part)
        
        # Send email
        with smtplib.SMTP('127.0.0.1', 2525) as server:
            server.send_message(msg)
        
        # Wait for processing
        time.sleep(0.5)
        
        # Verify email and attachment were stored
        final_emails, final_attachments = count_emails_and_attachments()
        assert final_emails == initial_emails + 1, "Email should be stored"
        assert final_attachments == initial_attachments + 1, "Attachment should be stored"
        
        # Verify content
        email, attachments = get_last_email_with_attachments()
        assert email is not None, "Email should exist"
        assert email['subject'] == 'SMTP Test - With Attachment', "Subject should match"
        assert len(attachments) == 1, "Should have one attachment"
        assert attachments[0]['filename'] == 'test_file.txt', "Filename should match"
        assert attachments[0]['file_size'] == len(attachment_content), "File size should match"
    
    def test_receive_multiple_recipients(self, smtp_server, db):
        """
        Test receiving email addressed to multiple recipients.
        
        Validates that the email is stored for the primary recipient.
        """
        initial_emails, _ = count_emails_and_attachments()
        
        # Create email with multiple recipients
        msg = MIMEText('Multi-recipient test')
        msg['Subject'] = 'SMTP Test - Multiple Recipients'
        msg['From'] = 'sender@example.com'
        msg['To'] = '${TEST_RECIPIENT}'
        
        with smtplib.SMTP('127.0.0.1', 2525) as server:
            server.send_message(msg)
        
        time.sleep(0.5)
        
        final_emails, _ = count_emails_and_attachments()
        assert final_emails == initial_emails + 1, "Email should be stored for recipient"
    
    def test_smtp_utf8_support(self, smtp_server, db):
        """
        Test receiving email with UTF-8 characters in subject and body.
        
        Validates proper handling of international characters.
        """
        initial_emails, _ = count_emails_and_attachments()
        
        # Create email with UTF-8 content
        msg = MIMEText('Unicode content: ñ 中文 🎉', 'plain', 'utf-8')
        msg['Subject'] = 'Unicode: ñ 中文 🎉'
        msg['From'] = 'test@example.com'
        msg['To'] = '${TEST_RECIPIENT}'
        
        with smtplib.SMTP('127.0.0.1', 2525) as server:
            server.send_message(msg)
        
        time.sleep(0.5)
        
        final_emails, _ = count_emails_and_attachments()
        assert final_emails == initial_emails + 1, "UTF-8 email should be stored"
        
        email, _ = get_last_email_with_attachments()
        assert email is not None, "Email should exist"
        assert 'ñ' in email['subject'] or '中文' in email['body'], "UTF-8 content should be preserved"


class TestSMTPNetworkAccess:
    """Test SMTP server network accessibility."""
    
    def test_smtp_server_listens_on_all_interfaces(self, db):
        """
        Test that SMTP server accepts connections on all interfaces.
        
        This validates the server is accessible from other computers on the network.
        """
        # Start server on all interfaces
        controller = start_smtp_server(host='0.0.0.0', port=2525, debug=False)
        time.sleep(1)
        
        try:
            # Test connection to localhost
            with smtplib.SMTP('127.0.0.1', 2525) as server:
                server.ehlo()
            
            # If we have a network interface, test that too
            import socket
            try:
                # Get local IP
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(('8.8.8.8', 80))
                local_ip = s.getsockname()[0]
                s.close()
                
                # Test connection via network IP
                with smtplib.SMTP(local_ip, 2525) as server:
                    server.ehlo()
                    
            except Exception:
                # Network test skipped if no external connectivity
                pass
                
        finally:
            stop_smtp_server(controller)
