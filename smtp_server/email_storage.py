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
from app.utils.emails import (
    compute_thread_id,
    extract_threading_headers,
    normalize_subject,
)
from app.utils.embedding_enqueue import enqueue_embedding_job

logger = logging.getLogger(__name__)

# Create uploads directory for attachments
UPLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'uploads')
os.makedirs(UPLOADS_DIR, exist_ok=True)


def extract_bodies(msg: EmailMessage) -> tuple:
    """
    Extract plain text and HTML bodies from email message.
    
    Returns:
        tuple: (plain_text, html)
    """
    plain_text = ""
    html = ""
    
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            
            # Skip attachments
            content_disposition = part.get('Content-Disposition', '')
            if 'attachment' in content_disposition:
                continue
            
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            
            try:
                decoded = payload.decode('utf-8')
            except:
                try:
                    decoded = payload.decode('latin-1')
                except:
                    continue
            
            if content_type == "text/plain" and not plain_text:
                plain_text = decoded
            elif content_type == "text/html" and not html:
                html = decoded
    else:
        # Single part email
        content_type = msg.get_content_type()
        payload = msg.get_payload(decode=True)
        if payload:
            try:
                decoded = payload.decode('utf-8')
            except:
                try:
                    decoded = payload.decode('latin-1')
                except:
                    decoded = str(msg.get_payload())
            
            if content_type == "text/html":
                html = decoded
            else:
                plain_text = decoded
    
    return plain_text, html


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


def save_attachments(msg, email_id: int, user_id: int, conn, cursor):
    """Extract and save attachments from email message.

    Saves attachment files to disk and stores metadata in the database.
    Uses savepoints so that attachment failures do not roll back
    the enclosing email transaction.
    """
    if not msg.is_multipart():
        return

    attachment_count = 0
    for part in msg.walk():
        content_disposition = part.get('Content-Disposition', '')
        content_id = part.get('Content-ID', '')

        is_attachment = 'attachment' in content_disposition
        is_inline_image = ('inline' in content_disposition and content_id) or \
            (part.get_content_maintype() == 'image' and content_id)

        if not is_attachment and not is_inline_image:
            continue
        if part.get_content_maintype() == 'multipart':
            continue

        filename = part.get_filename()
        if not filename:
            filename = f"attachment_{uuid.uuid4().hex[:8]}.bin"

        content_type = part.get_content_type()

        try:
            data = part.get_payload(decode=True)
            if not data:
                continue

            file_size = len(data)

            unique_filename = str(uuid.uuid4())
            ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
            if ext:
                unique_filename += '.' + ext
            file_path = os.path.join(UPLOADS_DIR, unique_filename)

            with open(file_path, 'wb') as f:
                f.write(data)

            cursor.execute('SAVEPOINT att_save')
            try:
                cursor.execute(
                    '''INSERT INTO attachments
                       (email_id, file_name, content_type, file_size, file_path)
                       VALUES (%s, %s, %s, %s, %s)''',
                    (email_id, filename, content_type, file_size, file_path)
                )
                cursor.execute('RELEASE SAVEPOINT att_save')
            except Exception:
                cursor.execute('ROLLBACK TO SAVEPOINT att_save')
                if os.path.exists(file_path):
                    os.remove(file_path)
                raise

            attachment_count += 1
            logger.info(f"Saved attachment: {filename} ({file_size} bytes) -> {file_path}")

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
        body, body_html = extract_bodies(message)
        
        # Get headers as string
        headers_str = ''
        for key, value in message.items():
            headers_str += f"{key}: {value}\n"
        
        # Find or create sender user (the actual sender of the email)
        # This is the FROM address, not the recipient
        sender_normalized = sender.lower().strip('<>"\'') if sender else 'unknown@unknown'
        cursor.execute('SELECT id FROM users WHERE email = %s', (sender_normalized,))
        sender_user = cursor.fetchone()
        
        if not sender_user:
            # Create user for sender if they don't exist
            sender_username = sender_normalized.split('@')[0] if '@' in sender_normalized else 'unknown'
            sender_domain = sender_normalized.split('@')[-1] if '@' in sender_normalized else 'unknown'
            try:
                cursor.execute(
                    'INSERT INTO users (email, password_hash, name, is_local, created_at) VALUES (%s, %s, %s, %s, %s) RETURNING id',
                    (sender_normalized, 'external_sender', sender_username, False, datetime.now(timezone.utc))
                )
                sender_user = cursor.fetchone()
                conn.commit()
                logger.info(f"Created sender user: {sender_normalized} with ID {sender_user['id']}")
            except:
                # User might have been created by another process, fetch again
                cursor.execute('SELECT id FROM users WHERE email = %s', (sender_normalized,))
                sender_user = cursor.fetchone()
        
        sender_id = sender_user['id']
        
        # Find or create recipient user (for folder assignment)
        cursor.execute('SELECT id FROM users WHERE email = %s', (recipient,))
        recipient_user = cursor.fetchone()
        
        if not recipient_user:
            # Use the domains table (same source as handler.py RCPT validation)
            # instead of a hardcoded list. Falls back to seed domains if DB is empty.
            from app.db import get_seed_domains
            try:
                cursor.execute('SELECT domain FROM domains ORDER BY domain')
                db_domains = {row['domain'].lower() for row in cursor.fetchall() if row.get('domain')}
                local_domains = db_domains if db_domains else set(get_seed_domains())
            except Exception:
                local_domains = set(get_seed_domains())
            recipient_domain = recipient.split('@')[-1].lower() if '@' in recipient else ''
            
            if recipient_domain in local_domains:
                cursor.execute(
                    'INSERT INTO users (email, password_hash, name, is_local, created_at) VALUES (%s, %s, %s, %s, %s) RETURNING id',
                    (recipient, 'test_hash', recipient.split('@')[0], True, datetime.now(timezone.utc))
                )
                recipient_user = cursor.fetchone()
                conn.commit()
        
        if not recipient_user:
            logger.warning(f"No user found for recipient: {recipient}")
            cursor.close()
            conn.close()
            return None
        
        user_id = recipient_user['id']
        
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
        
        # Sanitize strings to remove NUL characters (0x00) which PostgreSQL rejects
        def sanitize_string(s):
            if s is None:
                return ''
            return s.replace('\x00', '')

        subject_clean = sanitize_string(subject)
        body_clean = sanitize_string(body)
        body_html_clean = sanitize_string(body_html)
        headers_clean = sanitize_string(headers_str)

        # Store raw email for future extraction
        raw_email_str = ''
        if raw_data:
            try:
                raw_email_str = sanitize_string(raw_data.decode('utf-8', errors='replace'))
            except:
                raw_email_str = sanitize_string(str(raw_data))

        # --- Threading (RFC 2822) ----------------------------------------------
        # Parse Message-ID / In-Reply-To / References from the raw wire bytes
        # (preferred) or the parsed EmailMessage as fallback. Compute
        # thread_id with the same priority used by the backfill script:
        #   References > In-Reply-To walk > subject+participants bucket.
        mid, irt, refs = extract_threading_headers(raw_email_str)
        subj_norm = normalize_subject(subject_clean)
        tid, _strategy = compute_thread_id(
            cursor,
            message_id=mid,
            in_reply_to=irt,
            references_chain=refs,
            candidate_root_id=None,  # new insert; parent has different email_id
            subject_normalized=subj_norm,
        )
        subject_normalized_value = subj_norm if subj_norm and not (mid or irt or refs) else None

        # Insert email with correct sender_id and recipient_id
        cursor.execute(
            '''INSERT INTO emails
               (sender_id, recipient_id, folder_id, subject, body, body_html,
                raw_email, headers, created_at, is_read,
                message_id, in_reply_to, references_chain, thread_id,
                subject_normalized)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s)
               RETURNING id''',
            (sender_id, user_id, folder_id, subject_clean, body_clean, body_html_clean,
             raw_email_str, headers_clean, datetime.now(timezone.utc), False,
             mid, irt, refs, tid, subject_normalized_value)
        )

        email_id = cursor.fetchone()['id']

        # Add recipient to email_recipients (the user who received this email)
        cursor.execute(
            'INSERT INTO email_recipients (email_id, user_id, recipient_type) VALUES (%s, %s, %s)',
            (email_id, user_id, 'to')
        )

        # PR1 — enqueue async embedding job (subject always; body only when
        # the folder is in the configured set). Defensive try/except — a
        # failure here must NOT prevent the SMTP DATA response.
        try:
            enqueue_embedding_job(email_id, folder_id=folder_id,
                                   user_id=user_id, reason='smtp_data')
        except Exception as _e:
            logger.warning("embedding enqueue failed for SMTP email %s: %s", email_id, _e)

        # Save any attachments
        save_attachments(message, email_id, user_id, conn, cursor)

        conn.commit()
        cursor.close()
        conn.close()

        logger.info(
            f"Email stored with ID: {email_id} (thread_id={tid}, message_id={mid!r})"
        )
        return email_id
        
    except Exception as e:
        logger.error(f"Error storing email: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None
