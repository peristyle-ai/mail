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

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from smtp_server import start_smtp_server, stop_smtp_server


def run_flask_app(port=5000, debug=False):
    """Run Flask app in a thread."""
    app = create_app()
    print(f"Starting Flask API on port {port}...")
    app.run(host='0.0.0.0', port=port, debug=debug, use_reloader=False)


def main():
    parser = argparse.ArgumentParser(description='Start Mail Server (Flask API + SMTP)')
    parser.add_argument('--flask-port', type=int, default=5000, help='Flask API port (default: 5000)')
    parser.add_argument('--smtp-port', type=int, default=587, help='SMTP server port (default: 587)')
    parser.add_argument('--smtp-host', default='0.0.0.0', help='SMTP bind address (default: 0.0.0.0)')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    
    args = parser.parse_args()
    
    print("="*70)
    print("Mail Server Startup")
    print("="*70)
    print()
    
    smtp_controller = None
    
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
        
        # Start Flask in a separate thread
        print(f"Starting Flask API on port {args.flask_port}...")
        flask_thread = threading.Thread(
            target=run_flask_app,
            args=(args.flask_port, args.debug),
            daemon=True
        )
        flask_thread.start()
        time.sleep(2)  # Give Flask time to start
        print(f"✓ Flask API started on port {args.flask_port}")
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
        print("Press Ctrl+C to stop both servers")
        print("="*70)
        print()
        
        # Keep running until interrupted
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n\nShutting down servers...")
        
    finally:
        if smtp_controller:
            print("Stopping SMTP server...")
            stop_smtp_server(smtp_controller)
            
        print("Servers stopped.")
        print("="*70)


if __name__ == '__main__':
    main()
