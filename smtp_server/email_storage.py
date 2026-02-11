"""Email storage - saves incoming emails to PostgreSQL."""

import email
import logging
from email.message import EmailMessage
from datetime import datetime, timezone
import sys
import os
import uuid

# Add parent directory to path to import app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import get_db_connection

logger = logging.getLogger(__name__)

# Create uploads directory for attachments
UPLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'uploads')
os.makedirs(UPLOADS_DIR, exist_ok=True)


def extract_email_body(msg: EmailMessage) -> str:
    """Extract text body from email message."""
    body = ""
    
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                try:
                    body = part.get_payload(decode=True).decode('utf-8')
                    break
                except:
                    try:
                        body = part.get_payload(decode=True).decode('latin-1')
                        break
                    except:
                        continue
    else:
        try:
            body = msg.get_payload(decode=True).decode('utf-8')
        except:
            try:
                body = msg.get_payload(decode=True).decode('latin-1')
            except:
                body = str(msg.get_payload())
    
    return body


def extract_subject(msg: EmailMessage) -> str:
    """Extract and decode subject from email."""
    subject = msg.get('Subject', '')
    if subject:
        # Decode MIME encoded words
        from email.header import decode_header
        decoded_parts = decode_header(subject)
        subject = ''
        for part, charset in decoded_parts:
            if isinstance(part, bytes):
                try:
                    subject += part.decode(charset or 'utf-8')
                except:
                    subject += part.decode('latin-1', errors='ignore')
            else:
                subject += part
    return subject


def save_attachments(msg, email_id: int, conn, cursor):
    """Extract and save attachments from email message."""
    if not msg.is_multipart():
        return
    
    attachment_count = 0
    for part in msg.walk():
        # Skip the message body parts
        content_disposition = part.get('Content-Disposition', '')
        if 'attachment' not in content_disposition:
            continue
        
        # Get attachment filename
        filename = part.get_filename()
        if not filename:
            filename = f"attachment_{uuid.uuid4().hex[:8]}.bin"
        
        # Get content type
        content_type = part.get_content_type()
        
        # Get attachment data
        try:
            data = part.get_payload(decode=True)
            if not data:
                continue
            
            file_size = len(data)
            
            # Save to database - schema uses filename (no underscore), file_path
            unique_filename = f"{uuid.uuid4().hex}_{filename}"
            file_path = os.path.join(UPLOADS_DIR, unique_filename)
            
            # Save to filesystem
            with open(file_path, 'wb') as f:
                f.write(data)
            
            # Save metadata to database
            cursor.execute(
                '''INSERT INTO attachments 
                   (email_id, user_id, filename, content_type, file_path, file_size) 
                   VALUES (%s, %s, %s, %s, %s, %s)''',
                (email_id, user_id, filename, content_type, file_path, file_size)
            )
            
            attachment_count += 1
            logger.info(f"Saved attachment: {filename} ({file_size} bytes)")
            
        except Exception as e:
            logger.error(f"Error saving attachment {filename}: {e}")
            continue
    
    if attachment_count > 0:
        logger.info(f"Saved {attachment_count} attachment(s) for email {email_id}")
    
    return attachment_count


def store_email(sender: str, recipient: str, message: EmailMessage, raw_data: bytes) -> int:
    """
    Store email in database.
    
    Args:
        sender: Email sender address
        recipient: Email recipient address
        message: Parsed email message
        raw_data: Raw email bytes
        
    Returns:
        Email ID if successful, None otherwise
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Extract email data
        subject = extract_subject(message)
        body = extract_email_body(message)
        
        # Get headers as string
        headers_str = ''
        for key, value in message.items():
            headers_str += f"{key}: {value}\n"
        
        # Find or create user based on recipient domain
        # For now, we'll accept emails for any user and store them
        # The user needs to exist in the database
        
        # Try to find user by email
        cursor.execute('SELECT id FROM users WHERE email = %s', (recipient,))
        user = cursor.fetchone()
        
        if not user:
            # Try to extract username from email (e.g., the operator@example.com.au -> the operator)
            username = recipient.split('@')[0] if '@' in recipient else recipient
            cursor.execute('SELECT id FROM users WHERE email = %s', (f"{username}@example.com",))
            user = cursor.fetchone()
        
        if not user:
            logger.warning(f"No user found for recipient: {recipient}")
            # For testing, create a default user if none exists
            cursor.execute(
                'INSERT INTO users (email, password_hash, name, created_at) VALUES (%s, %s, %s, %s) RETURNING id',
                (recipient, 'test_hash', recipient.split('@')[0], datetime.now(timezone.utc))
            )
            user = cursor.fetchone()
            conn.commit()
            logger.info(f"Created user {recipient} with ID {user['id']}")
        
        user_id = user['id']
        
        # Get or create default inbox folder
        cursor.execute('SELECT id FROM folders WHERE user_id = %s AND name = %s', (user_id, 'Inbox'))
        folder = cursor.fetchone()
        
        if not folder:
            cursor.execute(
                'INSERT INTO folders (user_id, name) VALUES (%s, %s) RETURNING id',
                (user_id, 'Inbox')
            )
            folder = cursor.fetchone()
            conn.commit()
        
        folder_id = folder['id']
        
        # Insert email
        cursor.execute(
            '''INSERT INTO emails 
               (sender_id, folder_id, subject, body, headers, created_at, is_read) 
               VALUES (%s, %s, %s, %s, %s, %s, %s) 
               RETURNING id''',
            (user_id, folder_id, subject, body, headers_str, datetime.now(timezone.utc), False)
        )
        
        email_id = cursor.fetchone()['id']
        
        # Add recipient to email_recipients (the user who received this email)
        cursor.execute(
            'INSERT INTO email_recipients (email_id, user_id, recipient_type) VALUES (%s, %s, %s)',
            (email_id, user_id, 'to')
        )
        
        # Save any attachments
        save_attachments(message, email_id, conn, cursor)
        
        conn.commit()
        cursor.close()
        conn.close()
        
        logger.info(f"Email stored with ID: {email_id}")
        return email_id
        
    except Exception as e:
        logger.error(f"Error storing email: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None
