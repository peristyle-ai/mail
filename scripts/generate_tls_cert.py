#!/usr/bin/env python3
"""
Generate self-signed TLS certificate for SMTP server.

Usage:
    python scripts/generate_tls_cert.py [hostname]

Example:
    python scripts/generate_tls_cert.py mail.example.com

This script generates a self-signed certificate for TLS/SSL encryption.
The certificate will be saved to certs/server.crt and certs/server.key.
"""

import sys
import os
from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).parent.parent


def generate_self_signed_cert(hostname='localhost', cert_dir=None):
    """
    Generate self-signed TLS certificate.
    
    Args:
        hostname: The hostname for the certificate (e.g., 'mail.example.com')
        cert_dir: Directory to save certificates (default: PROJECT_ROOT/certs)
        
    Returns:
        Tuple of (cert_path, key_path)
    """
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from datetime import datetime, timezone, timedelta
        
        # Set certificate paths
        if cert_dir is None:
            cert_dir = PROJECT_ROOT / 'certs'
        else:
            cert_dir = Path(cert_dir)
        
        cert_path = cert_dir / 'server.crt'
        key_path = cert_dir / 'server.key'
        
        # Create directory if needed
        cert_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"Generating 2048-bit RSA key...")
        
        # Generate key
        key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048
        )
        
        print(f"Creating certificate for: {hostname}")
        
        # Generate certificate
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COUNTRY_NAME, 'AU'),
            x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, 'State'),
            x509.NameAttribute(NameOID.LOCALITY_NAME, 'City'),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, 'Mail Server'),
            x509.NameAttribute(NameOID.COMMON_NAME, hostname),
        ])
        
        cert = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            issuer
        ).public_key(
            key.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            datetime.now(timezone.utc)
        ).not_valid_after(
            datetime.now(timezone.utc) + timedelta(days=365)
        ).add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName(hostname),
                x509.DNSName(f'*.{hostname}'),
                x509.DNSName('localhost'),
                x509.DNSName('127.0.0.1'),
            ]),
            critical=False
        ).sign(key, hashes.SHA256())
        
        # Write certificate
        with open(cert_path, 'wb') as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        
        # Write key
        with open(key_path, 'wb') as f:
            f.write(key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption()
            ))
        
        return str(cert_path), str(key_path)
        
    except ImportError:
        raise ImportError("cryptography library not installed. Run: pip install cryptography")
    except Exception as e:
        raise RuntimeError(f"Failed to generate certificate: {e}")


def main():
    """Generate self-signed certificate."""
    hostname = sys.argv[1] if len(sys.argv) > 1 else 'localhost'
    
    print(f"Generating self-signed TLS certificate for: {hostname}")
    print(f"Project root: {PROJECT_ROOT}")
    print()
    
    try:
        cert_path, key_path = generate_self_signed_cert(hostname)
        print(f"✓ Certificate generated successfully!")
        print(f"  Certificate: {cert_path}")
        print(f"  Private Key: {key_path}")
        print()
        print("Configuration for config.yaml:")
        print(f"  security:")
        print(f"    tls:")
        print(f"      cert_path: certs/server.crt")
        print(f"      key_path: certs/server.key")
        print()
        print("Environment variables (optional overrides):")
        print(f"  export SMTP_TLS_CERT_PATH={cert_path}")
        print(f"  export SMTP_TLS_KEY_PATH={key_path}")
        print()
        print("Note: Browsers and email clients will show a warning for self-signed certificates.")
        print("For production, use Let's Encrypt or a commercial certificate.")
        print()
        print("To verify the certificate:")
        print(f"  openssl x509 -in {cert_path} -text -noout")
        
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
