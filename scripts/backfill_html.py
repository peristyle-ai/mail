#!/usr/bin/env python3
"""
Backfill HTML bodies for existing emails that have raw_email content stored.

This script processes emails where body_html is NULL but raw_email is present,
extracting the HTML content from the raw MIME message.

Usage:
    python scripts/backfill_html.py
    python scripts/backfill_html.py --dry-run
    python scripts/backfill_html.py --limit 10
"""

import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import get_db_connection
from smtp_server.email_storage import extract_bodies
from email import message_from_string


def backfill_html_bodies(dry_run: bool = False, limit: int = None):
    """
    Re-process stored raw emails to extract HTML content.
    
    Args:
        dry_run: If True, don't update database
        limit: Maximum number of emails to process
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Find emails with raw_email but no body_html
    query = '''
        SELECT id, subject, raw_email 
        FROM emails 
        WHERE raw_email IS NOT NULL 
        AND raw_email != ''
        AND (body_html IS NULL OR body_html = '')
        ORDER BY id DESC
    '''
    if limit:
        query += f' LIMIT {limit}'
    
    cursor.execute(query)
    emails = cursor.fetchall()
    
    print(f"Found {len(emails)} emails to process")
    
    processed = 0
    updated = 0
    errors = 0
    
    for email in emails:
        email_id = email['id']
        subject = email['subject']
        raw_email = email['raw_email']
        
        try:
            # Parse the raw email
            msg = message_from_string(raw_email)
            
            # Extract HTML body
            plain_text, html_body = extract_bodies(msg)
            
            if html_body:
                print(f"Email {email_id}: Found HTML ({len(html_body)} bytes)")
                print(f"  Subject: {subject[:60] if subject else 'None'}...")
                
                if not dry_run:
                    # Update database
                    cursor.execute(
                        'UPDATE emails SET body_html = %s WHERE id = %s',
                        (html_body, email_id)
                    )
                    conn.commit()
                    updated += 1
                else:
                    print(f"  [DRY RUN] Would update body_html")
            else:
                print(f"Email {email_id}: No HTML found (plain text only)")
                
            processed += 1
            
        except Exception as e:
            print(f"Email {email_id}: ERROR - {e}")
            errors += 1
    
    cursor.close()
    conn.close()
    
    print(f"\nSummary:")
    print(f"  Processed: {processed}")
    print(f"  Updated: {updated if not dry_run else 0} (dry run)")
    print(f"  Errors: {errors}")


def check_raw_email_availability():
    """Check how many emails have raw_email content stored."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE raw_email IS NOT NULL AND raw_email != '') as with_raw,
            COUNT(*) FILTER (WHERE body_html IS NOT NULL AND body_html != '') as with_html,
            COUNT(*) FILTER (WHERE subject ILIKE '%medium%' OR subject ILIKE '%digest%') as medium_digests
        FROM emails
    ''')
    
    result = cursor.fetchone()
    
    print("Email HTML Status:")
    print(f"  Total emails: {result['total']}")
    print(f"  With raw_email stored: {result['with_raw']}")
    print(f"  With HTML extracted: {result['with_html']}")
    print(f"  Medium/digest emails: {result['medium_digests']}")
    
    cursor.close()
    conn.close()
    
    return result


def main():
    parser = argparse.ArgumentParser(description='Backfill HTML bodies from raw emails')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without updating')
    parser.add_argument('--limit', type=int, default=None, help='Maximum emails to process')
    parser.add_argument('--status', action='store_true', help='Show status only')
    
    args = parser.parse_args()
    
    if args.status:
        check_raw_email_availability()
        return
    
    # Show status first
    status = check_raw_email_availability()
    
    if status['with_raw'] == 0:
        print("\nNo emails with raw_email content found.")
        print("Raw email storage was not enabled when these emails were received.")
        print("Future emails will have raw_email content stored and can be backfilled.")
        return
    
    print()
    backfill_html_bodies(dry_run=args.dry_run, limit=args.limit)


if __name__ == '__main__':
    main()
