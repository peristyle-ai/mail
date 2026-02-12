#!/usr/bin/env python3
"""
Generate self-signed TLS certificate for SMTP server.

Usage:
    python scripts/generate_tls_cert.py [hostname]

Example:
    python scripts/generate_tls_cert.py mail.example.com
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from smtp_server.security import TLSConfig


def main():
    """Generate self-signed certificate."""
    hostname = sys.argv[1] if len(sys.argv) > 1 else 'localhost'
    
    print(f"Generating self-signed TLS certificate for: {hostname}")
    print()
    
    tls = TLSConfig()
    
    try:
        cert_path, key_path = tls.generate_self_signed_cert(hostname)
        print(f"✓ Certificate generated successfully!")
        print(f"  Certificate: {cert_path}")
        print(f"  Private Key: {key_path}")
        print()
        print("To use this certificate:")
        print(f"  export SMTP_TLS_CERT_PATH={cert_path}")
        print(f"  export SMTP_TLS_KEY_PATH={key_path}")
        print()
        print("Note: Browsers and email clients will show a warning for self-signed certificates.")
        print("For production, use Let's Encrypt or a commercial certificate.")
        
    except ImportError as e:
        print(f"✗ Error: {e}")
        print()
        print("Please install the cryptography library:")
        print("  pip install cryptography")
        sys.exit(1)
    except Exception as e:
        print(f"✗ Error generating certificate: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
