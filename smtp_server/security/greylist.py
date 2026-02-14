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
import ipaddress

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import get_db_connection

logger = logging.getLogger(__name__)

# Major email providers that use multiple IPs
MAJOR_PROVIDERS = {
    'gmail.com',
    'googlemail.com',
    'google.com',
    'outlook.com',
    'hotmail.com',
    'live.com',
    'msn.com',
    'yahoo.com',
    'ymail.com',
    'aol.com',
    'protonmail.com',
    'icloud.com',
    'me.com',
}


class GreylistManager:
    """
    Greylisting implementation for SMTP server.
    
    Tracks (client_ip, sender, recipient) triplets.
    First-time combinations are temporarily rejected.
    After successful retry, whitelisted for 30 days.
    
    For major providers (Gmail, Outlook, etc.), checks by /24 subnet
    to handle their rotating IP pools.
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
            f"delay={delay_minutes}min, whitelist={whitelist_days}days, "
            f"major_providers={len(MAJOR_PROVIDERS)}"
        )
    
    def _is_major_provider(self, sender: str) -> bool:
        """Check if sender is from a major email provider."""
        try:
            domain = sender.split('@')[-1].lower()
            return domain in MAJOR_PROVIDERS
        except:
            return False
    
    def _get_ip_network(self, client_ip: str, prefix: int = 24) -> str:
        """Get network prefix for IP to handle rotating IPs from major providers."""
        try:
            ip_obj = ipaddress.ip_address(client_ip)
            if isinstance(ip_obj, ipaddress.IPv4Address):
                network = ipaddress.ip_network(f"{client_ip}/{prefix}", strict=False)
                return str(network.network_address)
            return client_ip  # For IPv6, keep full address
        except:
            return client_ip
    
    def check_sender(
        self,
        client_ip: str,
        sender: str,
        recipient: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if sender should be greylisted.
        
        For major providers, checks by /24 subnet to handle rotating IPs.
        For others, checks exact IP.
        
        Returns:
            (allowed, message) - allowed is True if email OK, False if greylisted
        """
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Determine search criteria based on sender type
            is_major = self._is_major_provider(sender)
            
            if is_major:
                # For major providers, search by /24 network
                ip_network = self._get_ip_network(client_ip, prefix=24)
                # Get first 3 octets for pattern matching
                ip_parts = client_ip.split('.')
                if len(ip_parts) == 4:
                    # IPv4 - use first 3 octets
                    subnet_pattern = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.%"
                    cursor.execute('''
                        SELECT id, whitelisted, first_seen, client_ip::text
                        FROM greylist 
                        WHERE sender = %s 
                        AND recipient = %s
                        AND (client_ip = %s OR client_ip::text LIKE %s)
                        ORDER BY first_seen DESC
                    ''', (sender, recipient, client_ip, subnet_pattern))
                    search_desc = f"subnet {ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.*"
                else:
                    # IPv6 or other - exact match
                    cursor.execute('''
                        SELECT id, whitelisted, first_seen, client_ip
                        FROM greylist 
                        WHERE sender = %s AND recipient = %s AND client_ip = %s
                    ''', (sender, recipient, client_ip))
                    search_desc = f"IP {client_ip}"
            else:
                # For regular senders, exact IP match
                cursor.execute('''
                    SELECT id, whitelisted, first_seen, client_ip
                    FROM greylist 
                    WHERE client_ip = %s AND sender = %s AND recipient = %s
                ''', (client_ip, sender, recipient))
                search_desc = f"IP {client_ip}"
            
            result = cursor.fetchone()
            
            # For major providers, check if any sender from this domain is already whitelisted
            if is_major and not result:
                sender_domain = sender.split('@')[-1].lower()
                cursor.execute('''
                    SELECT id FROM greylist 
                    WHERE sender LIKE %s 
                    AND recipient = %s 
                    AND whitelisted = TRUE
                    LIMIT 1
                ''', (f'%@{sender_domain}', recipient))
                any_whitelisted = cursor.fetchone()
                if any_whitelisted:
                    # Auto-whitelist this new sender from same domain
                    cursor.execute('''
                        INSERT INTO greylist (client_ip, sender, recipient, first_seen, whitelisted)
                        VALUES (%s, %s, %s, %s, TRUE)
                        ON CONFLICT (client_ip, sender, recipient) DO UPDATE SET whitelisted = TRUE
                    ''', (client_ip, sender, recipient, datetime.now(timezone.utc)))
                    conn.commit()
                    cursor.close()
                    conn.close()
                    logger.info(f"Greylist: Auto-whitelisted {sender} (any {sender_domain} sender already whitelisted)")
                    return True, None
            
            if result:
                entry_id = result['id']
                whitelisted = result['whitelisted']
                first_seen = result['first_seen']
                
                if whitelisted:
                    # Already whitelisted - record this IP if different
                    if result['client_ip'] != client_ip:
                        cursor.execute('''
                            INSERT INTO greylist (client_ip, sender, recipient, first_seen, whitelisted)
                            VALUES (%s, %s, %s, %s, TRUE)
                            ON CONFLICT (client_ip, sender, recipient) DO NOTHING
                        ''', (client_ip, sender, recipient, datetime.now(timezone.utc)))
                    else:
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
                    # Also record current IP if different
                    if result['client_ip'] != client_ip:
                        cursor.execute('''
                            INSERT INTO greylist (client_ip, sender, recipient, first_seen, whitelisted)
                            VALUES (%s, %s, %s, %s, TRUE)
                            ON CONFLICT (client_ip, sender, recipient) DO UPDATE SET whitelisted = TRUE
                        ''', (client_ip, sender, recipient, datetime.now(timezone.utc)))
                    conn.commit()
                    cursor.close()
                    conn.close()
                    logger.info(f"Greylist: Whitelisted {sender} -> {recipient} ({search_desc})")
                    return True, None
                else:
                    # Still in greylist period
                    remaining = self.delay_minutes - int(elapsed.total_seconds() / 60)
                    cursor.close()
                    conn.close()
                    logger.debug(f"Greylist: Rejecting {sender}, {remaining}min remaining ({search_desc})")
                    return False, f"Greylisted. Retry in {remaining} minutes."
            else:
                # New triplet - create entry and reject
                cursor.execute('''
                    INSERT INTO greylist (client_ip, sender, recipient, first_seen, whitelisted)
                    VALUES (%s, %s, %s, %s, FALSE)
                    ON CONFLICT (client_ip, sender, recipient) DO NOTHING
                ''', (client_ip, sender, recipient, datetime.now(timezone.utc)))
                conn.commit()
                cursor.close()
                conn.close()
                logger.info(f"Greylist: New entry for {sender} -> {recipient} ({search_desc})")
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
