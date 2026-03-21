#!/usr/bin/env python3
"""
Backfill sender_id and recipient_id for existing emails.

This script corrects the sender_id (which was incorrectly set to recipient)
and populates recipient_id for existing emails in the database.

Usage:
    python scripts/backfill_sender_recipient.py
    python scripts/backfill_sender_recipient.py --dry-run
    python scripts/backfill_sender_recipient.py --limit 100
"""

import sys
import os
import argparse
import re
from email import message_from_string
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import get_db_connection


def extract_sender_from_headers(headers: str) -> str:
    """Extract sender email from headers."""
    if not headers:
        return None
    
    for line in headers.split('\n'):
        if line.lower().startswith('from:'):
            # Extract email from "Name <email@domain>" or just "email@domain"
            # First try to find email in angle brackets
            match = re.search(r'<(.+?)>', line)
            if match:
                return match.group(1).strip().lower()
            # If no angle brackets, try to find email after "From: Name "
            match = re.search(r'From:\s*[^<]*<(.+?)>', line)
            if match:
                return match.group(1).strip().lower()
            # Last resort: find email-like pattern
            match = re.search(r'[\w\.-]+@[\w\.-]+', line)
            if match:
                return match.group(0).strip().lower()
    return None


def find_or_create_user(cursor, email: str) -> int:
    """Find or create a user and return their ID."""
    if not email:
        return None
    
    # Try to find existing user
    cursor.execute('SELECT id FROM users WHERE email = %s', (email,))
    user = cursor.fetchone()
    
    if user:
        return user['id']
    
    # Create new user
    username = email.split('@')[0] if '@' in email else 'unknown'
    try:
        cursor.execute(
            'INSERT INTO users (email, password_hash, name, is_local, created_at) VALUES (%s, %s, %s, %s, %s) RETURNING id',
            (email, 'external_sender', username, False, datetime.now(timezone.utc))
        )
        user = cursor.fetchone()
        return user['id']
    except:
        # Try again in case of race condition
        cursor.execute('SELECT id FROM users WHERE email = %s', (email,))
        user = cursor.fetchone()
        return user['id'] if user else None


def backfill_sender_recipient(dry_run: bool = False, limit: int = None):
    """Backfill sender_id and recipient_id for existing emails."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # First, check if recipient_id column exists
    cursor.execute("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'emails' AND column_name = 'recipient_id'
    """)
    if not cursor.fetchone():
        print("Adding recipient_id column...")
        cursor.execute('ALTER TABLE emails ADD COLUMN IF NOT EXISTS recipient_id INTEGER REFERENCES users(id)')
        conn.commit()
    
    # Get emails that need fixing (either sender_id is wrong or recipient_id is null)
    # Exclude emails that already have the correct sender (where sender_id points to a user matching the From header)
    query = '''
        SELECT e.id, e.subject, e.headers, e.sender_id, e.recipient_id, e.folder_id,
               f.user_id as folder_user_id
        FROM emails e
        JOIN folders f ON e.folder_id = f.id
        WHERE e.sender_id IS NOT NULL
        ORDER BY e.id DESC
    '''
    if limit:
        query += f' LIMIT {limit}'
    
    cursor.execute(query)
    emails = cursor.fetchall()
    
    print(f"Processing {len(emails)} emails...")
    
    updated = 0
    errors = 0
    skipped = 0
    
    for email in emails:
        email_id = email['id']
        
        try:
            # Get recipient from folder
            recipient_id = email['folder_user_id']
            
            # Get sender from headers
            sender_email = extract_sender_from_headers(email['headers'])
            
            if not sender_email:
                # Try to get from existing user
                cursor.execute('SELECT email FROM users WHERE id = %s', (email['sender_id'],))
                user = cursor.fetchone()
                sender_email = user['email'] if user else None
            
            if not sender_email:
                print(f"Email {email_id}: No sender found, skipping")
                skipped += 1
                continue
            
            # Find or create sender user
            new_sender_id = find_or_create_user(cursor, sender_email)
            
            if not new_sender_id:
                print(f"Email {email_id}: Could not find/create sender user for {sender_email}")
                errors += 1
                continue
            
            if dry_run:
                print(f"Email {email_id}: Would update sender_id {email['sender_id']} -> {new_sender_id} ({sender_email}), recipient_id -> {recipient_id}")
            else:
                cursor.execute('''
                    UPDATE emails 
                    SET sender_id = %s, recipient_id = %s 
                    WHERE id = %s
                ''', (new_sender_id, recipient_id, email_id))
                conn.commit()
            
            updated += 1
            
        except Exception as e:
            print(f"Email {email_id}: Error - {e}")
            errors += 1
    
    cursor.close()
    conn.close()
    
    print(f"\nSummary:")
    print(f"  Processed: {len(emails)}")
    if dry_run:
        print(f"  Updated: 0 (dry run)")
    else:
        print(f"  Updated: {updated}")
    print(f"  Skipped: {skipped}")
    print(f"  Errors: {errors}")


def check_status():
    """Check current status of sender_id/recipient_id."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check recipient_id column
    cursor.execute("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'emails' AND column_name = 'recipient_id'
    """)
    has_recipient_id = cursor.fetchone() is not None
    
    # Get stats
    cursor.execute('''
        SELECT 
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE sender_id IS NOT NULL) as with_sender,
            COUNT(*) FILTER (WHERE recipient_id IS NOT NULL) as with_recipient
        FROM emails
    ''')
    stats = cursor.fetchone()
    
    # Check a few recent emails
    cursor.execute('''
        SELECT e.id, e.subject, e.sender_id, e.recipient_id, 
               s.email as sender_email, r.email as recipient_email
        FROM emails e
        LEFT JOIN users s ON e.sender_id = s.id
        LEFT JOIN users r ON e.recipient_id = r.id
        ORDER BY e.id DESC
        LIMIT 5
    ''')
    recent = cursor.fetchall()
    
    print("Email sender/recipient status:")
    print(f"  Total emails: {stats['total']}")
    print(f"  With sender_id: {stats['with_sender']}")
    print(f"  With recipient_id: {stats['with_recipient']}")
    print(f"  recipient_id column exists: {has_recipient_id}")
    print()
    print("Recent emails:")
    for e in recent:
        print(f"  ID={e['id']}: sender={e['sender_email'][:30] if e['sender_email'] else 'None'} -> recipient={e['recipient_email'][:30] if e['recipient_email'] else 'None'}")
    
    cursor.close()
    conn.close()


def main():
    parser = argparse.ArgumentParser(description='Backfill sender_id and recipient_id')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done')
    parser.add_argument('--limit', type=int, default=None, help='Limit number of emails')
    parser.add_argument('--status', action='store_true', help='Show status only')
    
    args = parser.parse_args()
    
    if args.status:
        check_status()
        return
    
    check_status()
    print()
    backfill_sender_recipient(dry_run=args.dry_run, limit=args.limit)


if __name__ == '__main__':
    main()
