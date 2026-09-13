#!/usr/bin/env python3
"""
Start both Flask API and SMTP servers.

Usage:
    python start_servers.py
    python start_servers.py --smtp-port 587 --flask-port 5000
"""

import sys
import os
import signal
import argparse
import threading
import time
import logging
import traceback
from logging.handlers import RotatingFileHandler

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.db import ensure_attachments_schema, ensure_domains_table, ensure_email_copy_schema, seed_local_domains
from smtp_server import start_smtp_server, stop_smtp_server
from smtp_server.outbound import OutboundQueueProcessor

# Get host from environment - must be set
SERVER_HOST = os.environ.get('HOST')
if not SERVER_HOST:
	raise ValueError("HOST environment variable is required. Set HOST in .env file.")

# Set up logging with rotation
log_formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
console_handler.setLevel(logging.INFO)

# File handler with rotation (10MB per file, keep 5 backups)
file_handler = RotatingFileHandler(
    '/tmp/mail_server.log',
    maxBytes=10*1024*1024,  # 10MB
    backupCount=5
)
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.DEBUG)

# Root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
root_logger.addHandler(console_handler)
root_logger.addHandler(file_handler)

logger = logging.getLogger(__name__)


def run_flask_app(port=5000, debug=False, ssl_context=None):
    """Run Flask app in a thread."""
    try:
        app = create_app()
        scheme = 'https' if ssl_context else 'http'
        logger.info(f"Starting Flask API on {scheme}://{SERVER_HOST}:{port}...")
        app.run(host=SERVER_HOST, port=port, debug=debug, use_reloader=False,
                ssl_context=ssl_context)
    except Exception as e:
        logger.error(f"Flask app crashed: {e}")
        logger.error(traceback.format_exc())
        raise


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    logger.info(f"Received signal {signum}, shutting down...")
    sys.exit(0)


def main():
    # Set up signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    parser = argparse.ArgumentParser(description='Start Mail Server (Flask API + SMTP)')
    parser.add_argument('--flask-port', type=int, default=5003, help='Flask API port (default: 5003)')
    parser.add_argument('--smtp-port', type=int, default=2525, help='SMTP server port (default: 2525, use 587 with sudo)')
    parser.add_argument('--smtp-host', default=SERVER_HOST, help='SMTP bind address (default: HOST from .env)')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    parser.add_argument('--tls-cert', default=os.environ.get('TLS_CERT', ''),
                        help='Path to TLS certificate (enables HTTPS on Flask API)')
    parser.add_argument('--tls-key', default=os.environ.get('TLS_KEY', ''),
                        help='Path to TLS private key (enables HTTPS on Flask API)')
    parser.add_argument('--smtp-tls-cert', default=os.environ.get('SMTP_TLS_CERT_PATH', ''),
                        help='Path to SMTP TLS certificate (enables STARTTLS)')
    parser.add_argument('--smtp-tls-key', default=os.environ.get('SMTP_TLS_KEY_PATH', ''),
                        help='Path to SMTP TLS private key (enables STARTTLS)')
    parser.add_argument('--require-starttls', action='store_true',
                        default=os.environ.get('SMTP_REQUIRE_STARTTLS', '').lower() == 'true',
                        help='Reject SMTP commands before STARTTLS upgrade')
    
    args = parser.parse_args()
    
    # Build Flask SSL context if cert+key provided
    ssl_context = None
    if args.tls_cert and args.tls_key:
        import ssl
        if not os.path.exists(args.tls_cert):
            raise FileNotFoundError(f"TLS cert not found: {args.tls_cert}")
        if not os.path.exists(args.tls_key):
            raise FileNotFoundError(f"TLS key not found: {args.tls_key}")
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_context.load_cert_chain(args.tls_cert, args.tls_key)
        print(f"Flask TLS enabled: {args.tls_cert}")
    
    # Build SMTP TLS context — reuse the same cert as Flask by default
    smtp_tls_context = None
    smtp_cert = args.smtp_tls_cert or args.tls_cert
    smtp_key = args.smtp_tls_key or args.tls_key
    if smtp_cert and smtp_key:
        import ssl as _ssl
        if os.path.exists(smtp_cert) and os.path.exists(smtp_key):
            smtp_tls_context = _ssl.SSLContext(_ssl.PROTOCOL_TLS_SERVER)
            smtp_tls_context.load_cert_chain(smtp_cert, smtp_key)
            print(f"SMTP STARTTLS enabled: {smtp_cert}")
        else:
            print(f"SMTP TLS cert/key not found — SMTP without TLS")
    
    print("="*70)
    print("Mail Server Startup")
    print("="*70)
    print()
    
    smtp_controller = None
    queue_processor = None
    
    try:
        try:
            ensure_attachments_schema()
            ensure_email_copy_schema()
            ensure_domains_table()
            seed_local_domains()
        except Exception as e:
            print(f"schema init skipped: {type(e).__name__}: {e}")

        # Start SMTP server
        smtp_tls_note = ' (STARTTLS)' if smtp_tls_context else ''
        print(f"Starting SMTP Server on {args.smtp_host}:{args.smtp_port}{smtp_tls_note}...")
        smtp_controller = start_smtp_server(
            host=args.smtp_host,
            port=args.smtp_port,
            debug=args.debug,
            tls_context=smtp_tls_context,
            require_starttls=args.require_starttls,
        )
        print(f"✓ SMTP Server started on {args.smtp_host}:{args.smtp_port}{smtp_tls_note}")
        print()
        
        # Start outbound queue processor
        print("Starting Outbound Queue Processor...")
        queue_processor = OutboundQueueProcessor(
            check_interval=30,
            max_retries=5
        )
        queue_processor.start()
        print("✓ Outbound Queue Processor started")
        print()
        
        # Start Flask in a daemon thread. Daemon=True is critical for
        # clean SIGTERM shutdown: the main thread signal handler does
        # sys.exit(0), which raises SystemExit. If the Flask thread
        # were non-daemon, Python would block waiting for it -- but
        # werkzeug app.run() never returns on its own, so the process
        # would hang until SIGKILL. Pre-fix, every restart needed
        # kill -9 after ~80s in deactivating (stop-sigterm).
        #
        # The "catch errors" goal is preserved by the is_alive()
        # check below -- the main loop still detects Flask thread
        # death and exits the process.
        logger.info(f"Starting Flask API on port {args.flask_port}...")
        flask_thread = threading.Thread(
            target=run_flask_app,
            args=(args.flask_port, args.debug, ssl_context),
            daemon=True
        )
        flask_thread.start()
        time.sleep(2)  # Give Flask time to start
        
        # Check if Flask thread is still alive
        if not flask_thread.is_alive():
            logger.error("Flask API failed to start!")
            raise RuntimeError("Flask API failed to start")
        
        logger.info(f"✓ Flask API started on port {args.flask_port}")
        print()
        
        scheme = 'https' if ssl_context else 'http'
        smtp_scheme = 'smtps' if args.require_starttls else 'smtp+starttls' if smtp_tls_context else 'smtp'
        print("="*70)
        print("Servers are running!")
        print("="*70)
        print()
        print("Access Points:")
        print(f"  - Swagger UI:    {scheme}://localhost:{args.flask_port}/docs")
        print(f"  - Flask API:     {scheme}://localhost:{args.flask_port}/api/")
        print(f"  - SMTP Server:   {args.smtp_host}:{args.smtp_port} ({smtp_scheme})")
        print()
        print("Test Commands:")
        print(f"  Local:  python scripts/send_test_email.py --server 127.0.0.1 --port {args.smtp_port}")
        print(f"  Network: python scripts/send_test_email.py --server 192.168.4.30 --port {args.smtp_port}")
        print()
        print("Outbound Email:")
        print(f"  Queue Processor: Running (checks every 30s)")
        print(f"  Retry Policy: 5 attempts with exponential backoff")
        print()
        print("Press Ctrl+C to stop all services")
        print("="*70)
        print()
        
        # Keep running until interrupted with error handling
        while True:
            try:
                time.sleep(1)
                # Check if Flask thread died
                if not flask_thread.is_alive():
                    logger.error("Flask API thread has died!")
                    raise RuntimeError("Flask API thread has died")
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                logger.error(traceback.format_exc())
                # Don't exit immediately, give time for cleanup
                time.sleep(5)
                raise
            
    except KeyboardInterrupt:
        print("\n\nShutting down servers...")
        
    finally:
        if queue_processor:
            print("Stopping outbound queue processor...")
            queue_processor.stop()
            
        if smtp_controller:
            print("Stopping SMTP server...")
            stop_smtp_server(smtp_controller)
            
        print("Servers stopped.")
        print("="*70)


if __name__ == '__main__':
    main()
