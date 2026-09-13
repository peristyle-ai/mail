"""SMTP Server setup and startup."""

import asyncio
import logging
import os
import ssl
from aiosmtpd.controller import Controller
from .handler import MailHandler

logger = logging.getLogger(__name__)


def _build_tls_context(cert_path: str = None, key_path: str = None) -> ssl.SSLContext | None:
    """Build an SSL context for the SMTP server.
    
    Uses the same cert as the Flask API by default (certs/server.crt + server.key).
    Override via SMTP_TLS_CERT_PATH / SMTP_TLS_KEY_PATH env vars.
    
    Returns None if certs are not found (SMTP runs without TLS).
    """
    project_root = os.getenv('PROJECT_ROOT', os.getcwd())
    cert = cert_path or os.getenv(
        'SMTP_TLS_CERT_PATH',
        os.path.join(project_root, 'certs', 'server.crt')
    )
    key = key_path or os.getenv(
        'SMTP_TLS_KEY_PATH',
        os.path.join(project_root, 'certs', 'server.key')
    )
    
    if not os.path.exists(cert):
        logger.info(f"SMTP TLS cert not found at {cert} — SMTP will run without TLS")
        return None
    if not os.path.exists(key):
        logger.info(f"SMTP TLS key not found at {key} — SMTP will run without TLS")
        return None
    
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        logger.info(f"SMTP TLS loaded: {cert}")
        return ctx
    except Exception as e:
        logger.error(f"Failed to load SMTP TLS certs: {e}")
        return None


def start_smtp_server(host='0.0.0.0', port=2525, debug=False,
                      tls_context: ssl.SSLContext | None = None,
                      require_starttls: bool = False):
    """
    Start the SMTP server.
    
    Args:
        host: Interface to bind to (0.0.0.0 for all interfaces)
        port: Port to listen on (587 is SMTP submission port)
        debug: Enable debug logging
        tls_context: SSL context for STARTTLS. If None, auto-discovers from
                     SMTP_TLS_CERT_PATH / SMTP_TLS_KEY_PATH env vars or
                     certs/server.crt + certs/server.key.
        require_starttls: If True, reject commands before STARTTLS upgrade.
                          If False (default), STARTTLS is offered but optional.
    
    Returns:
        Controller instance
    """
    if debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)
    
    # Auto-discover TLS context if not provided
    if tls_context is None:
        tls_context = _build_tls_context()
    
    handler = MailHandler()
    
    # Build controller kwargs — only pass TLS params if we have a context
    smtp_kwargs = {
        'hostname': host,
        'port': port,
        'enable_SMTPUTF8': True,
    }
    if tls_context:
        smtp_kwargs['tls_context'] = tls_context
        smtp_kwargs['require_starttls'] = require_starttls
    
    controller = Controller(handler, **smtp_kwargs)
    
    controller.start()
    tls_status = 'STARTTLS available' if tls_context else 'no TLS'
    if require_starttls and tls_context:
        tls_status = 'STARTTLS required'
    logger.info(f"SMTP Server started on {host}:{port} ({tls_status})")
    
    return controller


def stop_smtp_server(controller):
    """Stop the SMTP server."""
    if controller:
        controller.stop()
        logger.info("SMTP Server stopped")


if __name__ == '__main__':
    # Test the SMTP server
    print("Starting SMTP server on port 2525...")
    print("Press Ctrl+C to stop")
    
    controller = start_smtp_server(debug=True)
    
    try:
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping SMTP server...")
        stop_smtp_server(controller)
