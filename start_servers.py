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
from smtp_server import start_smtp_server, stop_smtp_server
from smtp_server.outbound import OutboundQueueProcessor

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


def run_flask_app(port=5000, debug=False):
    """Run Flask app in a thread."""
    try:
        app = create_app()
        logger.info(f"Starting Flask API on port {port}...")
        app.run(host='0.0.0.0', port=port, debug=debug, use_reloader=False)
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
    parser.add_argument('--smtp-host', default='0.0.0.0', help='SMTP bind address (default: 0.0.0.0)')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    
    args = parser.parse_args()
    
    print("="*70)
    print("Mail Server Startup")
    print("="*70)
    print()
    
    smtp_controller = None
    queue_processor = None
    
    try:
        # Start SMTP server
        print(f"Starting SMTP Server on {args.smtp_host}:{args.smtp_port}...")
        smtp_controller = start_smtp_server(
            host=args.smtp_host,
            port=args.smtp_port,
            debug=args.debug
        )
        print(f"✓ SMTP Server started on {args.smtp_host}:{args.smtp_port}")
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
        
        # Start Flask in a separate thread (non-daemon to catch errors)
        logger.info(f"Starting Flask API on port {args.flask_port}...")
        flask_thread = threading.Thread(
            target=run_flask_app,
            args=(args.flask_port, args.debug),
            daemon=False  # Changed to non-daemon so we can catch errors
        )
        flask_thread.start()
        time.sleep(2)  # Give Flask time to start
        
        # Check if Flask thread is still alive
        if not flask_thread.is_alive():
            logger.error("Flask API failed to start!")
            raise RuntimeError("Flask API failed to start")
        
        logger.info(f"✓ Flask API started on port {args.flask_port}")
        print()
        
        print("="*70)
        print("Servers are running!")
        print("="*70)
        print()
        print("Access Points:")
        print(f"  - Swagger UI:    http://localhost:{args.flask_port}/docs")
        print(f"  - Flask API:     http://localhost:{args.flask_port}/api/")
        print(f"  - SMTP Server:   {args.smtp_host}:{args.smtp_port}")
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
