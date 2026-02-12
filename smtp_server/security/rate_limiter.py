"""
Rate Limiter for SMTP Server

Prevents abuse by limiting connections and emails per IP address.
Uses in-memory storage with automatic cleanup.
"""

import time
import logging
from collections import defaultdict
from typing import Dict, Tuple, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class IPTracker:
    """Tracks activity for a single IP address."""
    
    def __init__(self):
        self.connections = 0
        self.emails_minute = []
        self.emails_hour = []
        self.first_seen = datetime.now()
        self.blocked_until = None
        self.violation_count = 0
    
    def add_email(self):
        """Record an email sent from this IP."""
        now = datetime.now()
        self.emails_minute.append(now)
        self.emails_hour.append(now)
        self._cleanup_old_entries()
    
    def _cleanup_old_entries(self):
        """Remove old entries outside the tracking window."""
        now = datetime.now()
        # Keep only last minute
        self.emails_minute = [
            t for t in self.emails_minute 
            if now - t < timedelta(minutes=1)
        ]
        # Keep only last hour
        self.emails_hour = [
            t for t in self.emails_hour 
            if now - t < timedelta(hours=1)
        ]
    
    def is_blocked(self) -> bool:
        """Check if this IP is currently blocked."""
        if self.blocked_until is None:
            return False
        if datetime.now() > self.blocked_until:
            self.blocked_until = None  # Auto-unblock
            return False
        return True
    
    def block(self, duration_minutes: int = 30):
        """Block this IP for a specified duration."""
        self.blocked_until = datetime.now() + timedelta(minutes=duration_minutes)
        self.violation_count += 1
        logger.warning(f"IP blocked for {duration_minutes} minutes (violation #{self.violation_count})")


class RateLimiter:
    """
    Rate limiter for SMTP connections and emails.
    
    Tracks per-IP:
    - Active connections
    - Emails per minute
    - Emails per hour
    - Violation history
    """
    
    def __init__(
        self,
        max_connections: int = 10,
        max_emails_per_minute: int = 30,
        max_emails_per_hour: int = 100,
        block_duration_minutes: int = 30
    ):
        self.max_connections = max_connections
        self.max_emails_per_minute = max_emails_per_minute
        self.max_emails_per_hour = max_emails_per_hour
        self.block_duration_minutes = block_duration_minutes
        
        # In-memory storage: IP -> IPTracker
        self._trackers: Dict[str, IPTracker] = {}
        self._lock = None  # Would use threading.Lock() if needed
        
        logger.info(
            f"Rate limiter initialized: "
            f"max_connections={max_connections}, "
            f"max_emails_per_minute={max_emails_per_minute}, "
            f"max_emails_per_hour={max_emails_per_hour}"
        )
    
    def _get_tracker(self, client_ip: str) -> IPTracker:
        """Get or create tracker for an IP."""
        if client_ip not in self._trackers:
            self._trackers[client_ip] = IPTracker()
        return self._trackers[client_ip]
    
    def check_connection_allowed(self, client_ip: str) -> Tuple[bool, Optional[str]]:
        """
        Check if a new connection is allowed from this IP.
        
        Returns:
            (allowed, reason) - allowed is True if connection OK, False if blocked
        """
        tracker = self._get_tracker(client_ip)
        
        # Check if IP is blocked
        if tracker.is_blocked():
            remaining = int((tracker.blocked_until - datetime.now()).total_seconds() / 60)
            return False, f"IP blocked. Try again in {remaining} minutes."
        
        # Check connection limit
        if tracker.connections >= self.max_connections:
            tracker.block(self.block_duration_minutes)
            return False, f"Too many concurrent connections. IP blocked for {self.block_duration_minutes} minutes."
        
        return True, None
    
    def add_connection(self, client_ip: str):
        """Record a new connection from this IP."""
        tracker = self._get_tracker(client_ip)
        tracker.connections += 1
        logger.debug(f"Connection added for {client_ip}. Total: {tracker.connections}")
    
    def remove_connection(self, client_ip: str):
        """Record a connection closed from this IP."""
        if client_ip in self._trackers:
            tracker = self._trackers[client_ip]
            tracker.connections = max(0, tracker.connections - 1)
            logger.debug(f"Connection removed for {client_ip}. Remaining: {tracker.connections}")
    
    def check_email_allowed(self, client_ip: str) -> Tuple[bool, Optional[str]]:
        """
        Check if sending an email is allowed from this IP.
        
        Returns:
            (allowed, reason) - allowed is True if email OK, False if blocked
        """
        tracker = self._get_tracker(client_ip)
        
        # Check if IP is blocked
        if tracker.is_blocked():
            remaining = int((tracker.blocked_until - datetime.now()).total_seconds() / 60)
            return False, f"IP blocked. Try again in {remaining} minutes."
        
        # Cleanup old entries before checking
        tracker._cleanup_old_entries()
        
        # Check rate limits
        if len(tracker.emails_minute) >= self.max_emails_per_minute:
            tracker.block(self.block_duration_minutes)
            return False, f"Rate limit exceeded: {self.max_emails_per_minute} emails per minute. IP blocked for {self.block_duration_minutes} minutes."
        
        if len(tracker.emails_hour) >= self.max_emails_per_hour:
            tracker.block(self.block_duration_minutes)
            return False, f"Rate limit exceeded: {self.max_emails_per_hour} emails per hour. IP blocked for {self.block_duration_minutes} minutes."
        
        return True, None
    
    def add_email(self, client_ip: str):
        """Record an email sent from this IP."""
        tracker = self._get_tracker(client_ip)
        tracker.add_email()
        logger.debug(
            f"Email recorded for {client_ip}. "
            f"Minute: {len(tracker.emails_minute)}, "
            f"Hour: {len(tracker.emails_hour)}"
        )
    
    def get_stats(self, client_ip: str) -> dict:
        """Get statistics for an IP address."""
        if client_ip not in self._trackers:
            return {
                'connections': 0,
                'emails_per_minute': 0,
                'emails_per_hour': 0,
                'blocked': False
            }
        
        tracker = self._trackers[client_ip]
        tracker._cleanup_old_entries()
        
        return {
            'connections': tracker.connections,
            'emails_per_minute': len(tracker.emails_minute),
            'emails_per_hour': len(tracker.emails_hour),
            'blocked': tracker.is_blocked(),
            'blocked_until': tracker.blocked_until.isoformat() if tracker.blocked_until else None,
            'violation_count': tracker.violation_count,
            'first_seen': tracker.first_seen.isoformat()
        }
    
    def cleanup_old_trackers(self, max_age_hours: int = 24):
        """Remove trackers for IPs that haven't been seen recently."""
        now = datetime.now()
        cutoff = now - timedelta(hours=max_age_hours)
        
        removed = 0
        for ip in list(self._trackers.keys()):
            tracker = self._trackers[ip]
            # Keep if actively connected or recently seen
            if tracker.connections == 0 and tracker.first_seen < cutoff:
                # Check if any recent emails
                if not tracker.emails_hour or all(
                    now - t > timedelta(hours=max_age_hours) 
                    for t in tracker.emails_hour
                ):
                    del self._trackers[ip]
                    removed += 1
        
        if removed > 0:
            logger.info(f"Cleaned up {removed} old IP trackers")
