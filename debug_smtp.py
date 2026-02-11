"""Debug SMTP handler to trace email flow."""

import email
import logging
import sys
from aiosmtpd.smtp import Envelope

# Setup logging to see all messages
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger(__name__)

# Import the handler
sys.path.insert(0, '/opt/py_pg_accounts/git/py_pg_email')
from smtp_server.handler import MailHandler
from smtp_server.email_storage import store_email

class DebugHandler(MailHandler):
    """Debug version that prints everything."""
    
    async def handle_DATA(self, server, session, envelope: Envelope):
        """Override to add debug output."""
        logger.info("=== HANDLE_DATA CALLED ===")
        logger.info(f"mail_from: {envelope.mail_from}")
        logger.info(f"rcpt_tos: {envelope.rcpt_tos}")
        logger.info(f"content type: {type(envelope.content)}")
        logger.info(f"content length: {len(envelope.content) if envelope.content else 0}")
        
        # Call parent method
        result = await super().handle_DATA(server, session, envelope)
        logger.info(f"=== HANDLE_DATA RETURNED: {result} ===")
        return result


if __name__ == '__main__':
    from aiosmtpd.controller import Controller
    
    print("Starting DEBUG SMTP server on port 2525...")
    print("Send an email to test and watch the output")
    print("Press Ctrl+C to stop\n")
    
    handler = DebugHandler()
    controller = Controller(handler, hostname='0.0.0.0', port=2525)
    controller.start()
    
    try:
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
        controller.stop()
