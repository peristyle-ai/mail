"""
Greylisting for SMTP Server

Temporarily rejects first-time senders to reduce spam.
Legitimate mail servers retry; spammers often don't.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import get_db_connection

logger = logging.getLogger(__name__)


class GreylistManager:
    """
    Greylisting implementation for SMTP server.
    
    Tracks (client_ip, sender, recipient) triplets.
    First-time combinations are temporarily rejected.
    After successful retry, whitelisted for 30 days.
    """
    
    def __init__(
        self,
        delay_minutes: int = 5,
        whitelist_days: int = 30,
        cleanup_interval_hours: int = 24
    ):
        self.delay_minutes = delay_minutes
        self.whitelist_days = whitelist_days
        self.cleanup_interval_hours = cleanup_interval_hours
        
        logger.info(
            f"Greylist manager initialized: "
            f"delay={delay_minutes}min, whitelist={whitelist_days}days"
        )
    
    def check_sender(
        self,
        client_ip: str,
        sender: str,
        recipient: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if sender should be greylisted.
        
        Returns:
            (allowed, message) - allowed is True if email OK, False if greylisted
        """
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Check if already whitelisted
            cursor.execute('''
                SELECT id, whitelisted, first_seen 
                FROM greylist 
                WHERE client_ip = %s AND sender = %s AND recipient = %s
            ''', (client_ip, sender, recipient))
            
            result = cursor.fetchone()
            
            if result:
                entry_id = result['id']
                whitelisted = result['whitelisted']
                first_seen = result['first_seen']
                
                if whitelisted:
                    # Update last seen
                    cursor.execute('''
                        UPDATE greylist 
                        SET retry_count = retry_count + 1 
                        WHERE id = %s
                    ''', (entry_id,))
                    conn.commit()
                    cursor.close()
                    conn.close()
                    return True, None
                
                # Not yet whitelisted - check if delay has passed
                elapsed = datetime.now(timezone.utc) - first_seen
                if elapsed >= timedelta(minutes=self.delay_minutes):
                    # Whitelist now
                    cursor.execute('''
                        UPDATE greylist 
                        SET whitelisted = TRUE, retry_count = retry_count + 1 
                        WHERE id = %s
                    ''', (entry_id,))
                    conn.commit()
                    cursor.close()
                    conn.close()
                    logger.info(f"Greylist: Whitelisted {sender} -> {recipient}")
                    return True, None
                else:
                    # Still in greylist period
                    remaining = self.delay_minutes - int(elapsed.total_seconds() / 60)
                    cursor.close()
                    conn.close()
                    logger.debug(f"Greylist: Rejecting {sender}, {remaining}min remaining")
                    return False, f"Greylisted. Retry in {remaining} minutes."
            else:
                # New triplet - create entry and reject
                cursor.execute('''
                    INSERT INTO greylist (client_ip, sender, recipient, first_seen, whitelisted)
                    VALUES (%s, %s, %s, %s, FALSE)
                ''', (client_ip, sender, recipient, datetime.now(timezone.utc)))
                conn.commit()
                cursor.close()
                conn.close()
                logger.info(f"Greylist: New entry for {sender} -> {recipient}")
                return False, f"Greylisted. Please retry in {self.delay_minutes} minutes."
                
        except Exception as e:
            logger.error(f"Greylist check error: {e}")
            # Fail open - allow email if greylist fails
            return True, None
    
    def cleanup_old_entries(self):
        """Remove old greylist entries."""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cutoff = datetime.now(timezone.utc) - timedelta(days=self.whitelist_days)
            
            cursor.execute('''
                DELETE FROM greylist 
                WHERE whitelisted = FALSE AND first_seen < %s
            ''', (cutoff,))
            
            removed = cursor.rowcount
            conn.commit()
            cursor.close()
            conn.close()
            
            if removed > 0:
                logger.info(f"Greylist cleanup: removed {removed} old entries")
                
        except Exception as e:
            logger.error(f"Greylist cleanup error: {e}")
    
    def get_stats(self) -> dict:
        """Get greylist statistics."""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute('SELECT COUNT(*) as total FROM greylist WHERE whitelisted = FALSE')
            result = cursor.fetchone()
            pending = result['total'] if result else 0
            
            cursor.execute('SELECT COUNT(*) as total FROM greylist WHERE whitelisted = TRUE')
            result = cursor.fetchone()
            whitelisted = result['total'] if result else 0
            
            cursor.close()
            conn.close()
            
            return {
                'pending': pending,
                'whitelisted': whitelisted,
                'total': pending + whitelisted
            }
        except:
            return {'pending': 0, 'whitelisted': 0, 'total': 0}
