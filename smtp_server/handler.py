"""SMTP Message Handler - processes incoming emails."""

import email
import logging
from email.message import EmailMessage
from aiosmtpd.smtp import Envelope
from .email_storage import store_email

logger = logging.getLogger(__name__)


class MailHandler:
    """Handles incoming SMTP messages."""
    
    async def handle_DATA(self, server, session, envelope: Envelope):
        """
        Handle incoming email data.
        
        Args:
            server: SMTP server instance
            session: Session info
            envelope: Contains mail_from, rcpt_tos, content
            
        Returns:
            SMTP response string
        """
        try:
            # Parse the email content
            mail_from = envelope.mail_from or 'unknown@localhost'
            rcpt_tos = envelope.rcpt_tos
            data = envelope.content
            
            # Parse email message - handle both str and bytes
            if isinstance(data, str):
                data = data.encode('utf-8')
            msg = email.message_from_bytes(data)
            
            logger.info(f"Received email from {mail_from} to {rcpt_tos}")
            
            # Store email in database for each recipient
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
                    logger.warning(f"Failed to store email for {recipient}")
            
            return '250 Message accepted for delivery'
            
        except Exception as e:
            logger.error(f"Error handling email: {e}")
            return '451 Local error in processing'
    
    async def handle_MAIL(self, server, session, envelope, address, options):
        """Handle MAIL FROM command."""
        envelope.mail_from = address
        return '250 OK'
    
    async def handle_RCPT(self, server, session, envelope, address, options):
        """Handle RCPT TO command - accept all recipients for now."""
        envelope.rcpt_tos.append(address)
        return '250 OK'
