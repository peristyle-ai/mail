"""SMTP Message Handler with Security Features."""

import email
import logging
from email.message import EmailMessage
from aiosmtpd.smtp import Envelope, Session
from .email_storage import store_email
from .security import (
    security_config,
    RateLimiter,
    SPFValidator,
    GreylistManager
)
from .blacklist_checker import check_ip_blacklisted, increment_blacklist_hit

logger = logging.getLogger(__name__)


class SecureMailHandler:
    """
    SMTP handler with integrated security features.
    
    Security features:
    - Rate limiting (connections per IP, emails per time period)
    - SPF validation (prevent email spoofing)
    - Greylisting (reduce spam from unknown senders)
    """
    
    def __init__(self):
        # Initialize security components
        self.rate_limiter = None
        self.spf_validator = None
        self.greylist_manager = None
        
        if security_config.rate_limit_enabled:
            self.rate_limiter = RateLimiter(
                max_connections=security_config.rate_limit_max_connections,
                max_emails_per_minute=security_config.rate_limit_max_emails_per_minute,
                max_emails_per_hour=security_config.rate_limit_max_emails_per_hour
            )
            logger.info("Rate limiting enabled")
        
        if security_config.spf_enabled:
            self.spf_validator = SPFValidator(
                reject_on_fail=security_config.spf_reject_fail
            )
            logger.info("SPF validation enabled")
        
        if security_config.greylist_enabled:
            self.greylist_manager = GreylistManager(
                delay_minutes=security_config.greylist_delay_minutes,
                whitelist_days=security_config.greylist_whitelist_days
            )
            logger.info("Greylisting enabled")
    
    def _get_client_ip(self, session: Session) -> str:
        """Extract client IP from session."""
        if hasattr(session, 'peer'):
            # aiosmtpd session has peer attribute (host, port)
            return session.peer[0]
        elif hasattr(session, 'remote_address'):
            return session.remote_address[0]
        return 'unknown'
    
    async def handle_DATA(self, server, session: Session, envelope: Envelope):
        """
        Handle incoming email data with security checks.
        
        Security checks performed:
        1. Rate limiting (emails per IP)
        2. SPF validation (sender authorization)
        3. Greylisting (unknown sender delay)
        4. Store email in database
        """
        try:
            client_ip = self._get_client_ip(session)
            mail_from = envelope.mail_from or 'unknown@localhost'
            rcpt_tos = envelope.rcpt_tos
            data = envelope.content
            
            # Handle bytes/str conversion
            if isinstance(data, str):
                data = data.encode('utf-8')
            msg = email.message_from_bytes(data)
            
            logger.info(f"Processing email from {mail_from} ({client_ip}) to {rcpt_tos}")
            
            # 0. Blacklist check (first - immediate rejection)
            is_blacklisted, blacklist_entry = check_ip_blacklisted(client_ip)
            if is_blacklisted:
                increment_blacklist_hit(client_ip)
                reason = blacklist_entry.get('reason', 'IP blacklisted') if blacklist_entry else 'IP blacklisted'
                logger.warning(f"Blacklisted IP {client_ip} attempted to send email - rejected: {reason}")
                return f'550 {reason}'
            
            # 1. Rate limiting check for emails
            if self.rate_limiter:
                allowed, reason = self.rate_limiter.check_email_allowed(client_ip)
                if not allowed:
                    logger.warning(f"Rate limit exceeded: {client_ip} - {reason}")
                    return f'450 {reason}'
            
            # 2. SPF validation
            if self.spf_validator:
                spf_result, spf_explanation = self.spf_validator.validate(client_ip, mail_from)
                logger.info(f"SPF result for {mail_from} from {client_ip}: {spf_result}")
                
                if spf_result == 'fail' and security_config.spf_reject_fail:
                    logger.warning(f"SPF fail - rejecting email from {mail_from}")
                    return f'550 SPF validation failed: {spf_explanation}'
                elif spf_result in ['fail', 'softfail']:
                    # Log but don't reject softfail
                    pass
            
            # 3. Greylisting check (per recipient)
            if self.greylist_manager:
                for recipient in rcpt_tos:
                    allowed, reason = self.greylist_manager.check_sender(
                        client_ip, mail_from, recipient
                    )
                    if not allowed:
                        logger.info(f"Greylisted: {mail_from} -> {recipient} ({reason})")
                        return f'450 {reason}'
            
            # 4. Record email in rate limiter
            if self.rate_limiter:
                self.rate_limiter.add_email(client_ip)
            
            # 5. Store email in database
            for recipient in rcpt_tos:
                email_id = store_email(
                    sender=mail_from,
                    recipient=recipient,
                    message=msg,
                    raw_data=data
                )
                
                if email_id:
                    logger.info(f"Stored email ID {email_id} for {recipient}")
                else:
                    logger.error(f"Failed to store email for {recipient}")
            
            return '250 Message accepted for delivery'
            
        except Exception as e:
            logger.error(f"Error handling email: {e}", exc_info=True)
            return '451 Local error in processing'
    
    async def handle_MAIL(self, server, session: Session, envelope: Envelope, address: str, options):
        """
        Handle MAIL FROM command with connection rate limiting.
        """
        client_ip = self._get_client_ip(session)
        
        # Rate limiting check for new connections
        if self.rate_limiter:
            # Add connection first
            self.rate_limiter.add_connection(client_ip)
            
            # Check if allowed
            allowed, reason = self.rate_limiter.check_connection_allowed(client_ip)
            if not allowed:
                logger.warning(f"Connection rejected: {client_ip} - {reason}")
                return f'450 {reason}'
        
        envelope.mail_from = address
        logger.debug(f"MAIL FROM: {address} from {client_ip}")
        return '250 OK'
    
    async def handle_RCPT(self, server, session: Session, envelope: Envelope, address: str, options):
        """Handle RCPT TO command."""
        envelope.rcpt_tos.append(address)
        logger.debug(f"RCPT TO: {address}")
        return '250 OK'
    
    async def handle_quit(self, server, session: Session, envelope: Envelope):
        """Clean up when client disconnects."""
        client_ip = self._get_client_ip(session)
        
        if self.rate_limiter:
            self.rate_limiter.remove_connection(client_ip)
            logger.debug(f"Connection closed for {client_ip}")
    
    def get_security_stats(self) -> dict:
        """Get security system statistics."""
        stats = {
            'rate_limiting': self.rate_limiter is not None,
            'spf': self.spf_validator is not None,
            'greylisting': self.greylist_manager is not None
        }
        
        if self.greylist_manager:
            stats['greylist_stats'] = self.greylist_manager.get_stats()
        
        return stats


# Backwards compatibility - alias for existing code
MailHandler = SecureMailHandler
