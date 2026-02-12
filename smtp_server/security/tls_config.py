"""
TLS/SSL Configuration for SMTP Server

Provides TLS encryption for SMTP connections.
"""

import os
import ssl
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class TLSConfig:
    """
    TLS configuration for SMTP server.
    
    Supports:
    - SMTPS (port 465) - TLS from connection start
    - STARTTLS (port 587) - upgrade to TLS after connection
    """
    
    def __init__(
        self,
        cert_path: str = None,
        key_path: str = None,
        force_tls: bool = False
    ):
        # Get project root from environment or use current working directory
        project_root = os.getenv('PROJECT_ROOT', os.getcwd())
        
        self.cert_path = cert_path or os.getenv(
            'SMTP_TLS_CERT_PATH',
            os.path.join(project_root, 'certs', 'server.crt')
        )
        self.key_path = key_path or os.getenv(
            'SMTP_TLS_KEY_PATH',
            os.path.join(project_root, 'certs', 'server.key')
        )
        self.force_tls = force_tls or os.getenv('SMTP_TLS_FORCE', 'false').lower() == 'true'
        
        self._context = None
        self._loaded = False
        
        logger.info(f"TLS config: cert={self.cert_path}, force={self.force_tls}")
    
    def load_certificates(self) -> bool:
        """Load TLS certificates. Returns True if successful."""
        try:
            if not os.path.exists(self.cert_path):
                logger.warning(f"TLS certificate not found: {self.cert_path}")
                return False
            
            if not os.path.exists(self.key_path):
                logger.warning(f"TLS key not found: {self.key_path}")
                return False
            
            # Create SSL context
            self._context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            self._context.load_cert_chain(self.cert_path, self.key_path)
            
            self._loaded = True
            logger.info("TLS certificates loaded successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load TLS certificates: {e}")
            return False
    
    @property
    def is_loaded(self) -> bool:
        """Check if certificates are loaded."""
        return self._loaded
    
    @property
    def ssl_context(self) -> Optional[ssl.SSLContext]:
        """Get SSL context for use with aiosmtpd."""
        if not self._loaded:
            self.load_certificates()
        return self._context
    
    def generate_self_signed_cert(self, hostname: str = 'localhost') -> Tuple[str, str]:
        """
        Generate self-signed certificate for testing.
        
        Returns:
            (cert_path, key_path)
        """
        try:
            from cryptography import x509
            from cryptography.x509.oid import NameOID
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import rsa
            import datetime
            
            # Create directory if needed
            cert_dir = os.path.dirname(self.cert_path)
            os.makedirs(cert_dir, exist_ok=True)
            
            # Generate key
            key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048
            )
            
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
                datetime.datetime.now(datetime.timezone.utc)
            ).not_valid_after(
                datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365)
            ).add_extension(
                x509.SubjectAlternativeName([
                    x509.DNSName(hostname),
                    x509.DNSName('*.{}'.format(hostname)),
                ]),
                critical=False
            ).sign(key, hashes.SHA256())
            
            # Write certificate
            with open(self.cert_path, 'wb') as f:
                f.write(cert.public_bytes(serialization.Encoding.PEM))
            
            # Write key
            with open(self.key_path, 'wb') as f:
                f.write(key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption()
                ))
            
            logger.info(f"Generated self-signed certificate: {self.cert_path}")
            return self.cert_path, self.key_path
            
        except ImportError:
            logger.error("cryptography library not installed. Cannot generate certificate.")
            raise
        except Exception as e:
            logger.error(f"Failed to generate certificate: {e}")
            raise
