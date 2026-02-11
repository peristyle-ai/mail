"""SMTP Server setup and startup."""

import asyncio
import logging
from aiosmtpd.controller import Controller
from .handler import MailHandler

logger = logging.getLogger(__name__)


def start_smtp_server(host='0.0.0.0', port=587, debug=False):
    """
    Start the SMTP server.
    
    Args:
        host: Interface to bind to (0.0.0.0 for all interfaces)
        port: Port to listen on (587 is SMTP submission port)
        debug: Enable debug logging
        
    Returns:
        Controller instance
    """
    if debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)
    
    handler = MailHandler()
    controller = Controller(
        handler,
        hostname=host,
        port=port,
        enable_SMTPUTF8=True
    )
    
    controller.start()
    logger.info(f"SMTP Server started on {host}:{port}")
    
    return controller


def stop_smtp_server(controller):
    """Stop the SMTP server."""
    if controller:
        controller.stop()
        logger.info("SMTP Server stopped")


if __name__ == '__main__':
    # Test the SMTP server
    print("Starting SMTP server on port 587...")
    print("Press Ctrl+C to stop")
    
    controller = start_smtp_server(debug=True)
    
    try:
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping SMTP server...")
        stop_smtp_server(controller)
