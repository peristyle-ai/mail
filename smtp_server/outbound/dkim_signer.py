"""
DKIM (DomainKeys Identified Mail) Implementation

Provides email signing for outbound messages to improve deliverability
and prevent spoofing.
"""

import dkim
import logging
import os
from typing import Optional, Dict
from email.message import EmailMessage

logger = logging.getLogger(__name__)


class DKIMSigner:
    """DKIM signer for outbound emails."""
    
    def __init__(
        self,
        domain: str,
        selector: str = "default",
        private_key_path: Optional[str] = None,
        key_size: int = 2048
    ):
        """
        Initialize DKIM signer.
        
        Args:
            domain: Domain to sign for (e.g., 'example.com.au')
            selector: DKIM selector (default: 'default')
            private_key_path: Path to private key file
            key_size: RSA key size (default: 2048)
        """
        self.domain = domain
        self.selector = selector
        self.key_size = key_size
        
        if private_key_path and os.path.exists(private_key_path):
            with open(private_key_path, 'rb') as f:
                self.private_key = f.read()
            logger.info(f"Loaded DKIM private key from {private_key_path}")
        else:
            self.private_key = None
            logger.warning(f"DKIM private key not found at {private_key_path}")
    
    def generate_keys(self, output_dir: str = "certs") -> tuple:
        """
        Generate new DKIM key pair.
        
        Returns:
            Tuple of (private_key_path, public_key_dns_record)
        """
        try:
            # Generate RSA key pair
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import rsa
            from cryptography.hazmat.backends import default_backend
            
            private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=self.key_size,
                backend=default_backend()
            )
            
            # Save private key
            private_key_pem = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()
            )
            
            os.makedirs(output_dir, exist_ok=True)
            private_path = os.path.join(output_dir, f"dkim_{self.selector}.pem")
            
            with open(private_path, 'wb') as f:
                f.write(private_key_pem)
            
            # Generate public key for DNS
            public_key = private_key.public_key()
            public_key_der = public_key.public_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )
            
            # Convert to base64
            import base64
            public_key_b64 = base64.b64encode(public_key_der).decode('ascii')
            
            # Format for DNS TXT record
            # Split into chunks of 255 characters max
            chunks = [public_key_b64[i:i+255] for i in range(0, len(public_key_b64), 255)]
            key_data = '" "'.join(chunks)
            
            dns_record = f"{self.selector}._domainkey.{self.domain}. IN TXT \"v=DKIM1; k=rsa; p={key_data}\""
            
            logger.info(f"Generated DKIM keys for {self.domain} (selector: {self.selector})")
            logger.info(f"Private key saved to: {private_path}")
            
            return private_path, dns_record
            
        except Exception as e:
            logger.error(f"Error generating DKIM keys: {e}")
            raise
    
    def sign_email(self, message) -> Optional[EmailMessage]:
        """
        Sign an email with DKIM.
        
        Args:
            message: Email message to sign (EmailMessage or Message)
            
        Returns:
            Signed email message or original if signing failed
        """
        if not self.private_key:
            logger.warning("DKIM signing skipped - no private key available")
            return message
        
        try:
            # Convert message to bytes
            # Use policy=default for proper line ending handling
            from email import policy
            
            # If it's already an EmailMessage, use it directly
            if isinstance(message, EmailMessage):
                msg_bytes = message.as_bytes(policy=policy.default)
            else:
                # For older Message objects, convert via string then encode
                msg_bytes = message.as_string().encode('utf-8')
            
            # Sign the message
            signature = dkim.sign(
                msg_bytes,
                self.selector.encode(),
                self.domain.encode(),
                self.private_key,
                include_headers=[b"from", b"to", b"subject", b"date"]
            )
            
            # Parse signature and add to message
            sig_str = signature.decode('ascii')
            
            # Add DKIM-Signature header (remove the header name if present)
            if sig_str.startswith('DKIM-Signature: '):
                sig_str = sig_str[16:]  # Remove 'DKIM-Signature: '
            
            # Remove any line breaks from signature - header values cannot contain CR/LF
            sig_str = sig_str.replace('\r', '').replace('\n', '').strip()
            
            message['DKIM-Signature'] = sig_str
            
            logger.debug(f"DKIM signed email for {self.domain}")
            return message
            
        except Exception as e:
            logger.error(f"DKIM signing failed: {e}")
            import traceback
            logger.debug(f"DKIM signing error trace: {traceback.format_exc()}")
            # Return original message if signing fails
            return message
    
    @staticmethod
    def get_dns_record_instructions(domain: str, selector: str = "default") -> str:
        """
        Get instructions for DNS record setup.
        
        Returns:
            String with DNS setup instructions
        """
        return f"""
DKIM DNS Record Setup Instructions
===================================

1. Generate DKIM keys using:
   python -c "from smtp_server.outbound.dkim_signer import DKIMSigner; 
   signer = DKIMSigner('{domain}', '{selector}'); 
   signer.generate_keys()"

2. Add the following DNS TXT record:
   
   Hostname: {selector}._domainkey.{domain}
   Type: TXT
   Value: (generated from step 1)
   
3. Test with:
   dig TXT {selector}._domainkey.{domain}

4. Wait for DNS propagation (up to 24 hours)

Note: The private key will be saved to certs/dkim_{selector}.pem
"""


def load_dkim_config(config_path: str = "config.yaml") -> Optional[DKIMSigner]:
	"""Load DKIM configuration from config file.
	
	Supports multi-domain configuration. The 'domains' list is checked first,
	then falls back to single 'domain' key for backwards compatibility.
	"""
	try:
		import yaml
		
		with open(config_path, 'r') as f:
			config = yaml.safe_load(f)
		
		dkim_config = config.get('dkim', {})
		
		if not dkim_config.get('enabled', False):
			logger.info("DKIM signing disabled in config")
			return None
		
		# Support multi-domain configuration
		domains_config = dkim_config.get('domains', [])
		if domains_config:
			# Return the first configured domain's signer as default
			# The caller should use MultiDomainDKIMSigner for multi-domain support
			for domain_conf in domains_config:
				domain = domain_conf.get('domain')
				selector = domain_conf.get('selector', 'default')
				private_key = domain_conf.get('private_key', f'certs/dkim_{selector}.pem')
				if domain:
					signer = DKIMSigner(
						domain=domain,
						selector=selector,
						private_key_path=private_key
					)
					if signer.private_key:
						logger.info(f"DKIM loaded for domain: {domain} (selector: {selector})")
						return signer
		
		# Single domain fallback (backwards compatible)
		domain = dkim_config.get('domain')
		selector = dkim_config.get('selector', 'default')
		private_key = dkim_config.get('private_key', f'certs/dkim_{selector}.pem')
		
		if not domain:
			logger.warning("DKIM domain not configured")
			return None
		
		signer = DKIMSigner(
			domain=domain,
			selector=selector,
			private_key_path=private_key
		)
		
		if not signer.private_key:
			logger.warning(f"DKIM private key not found at {private_key}")
			logger.info("Run key generation first")
		
		return signer
		
	except Exception as e:
		logger.error(f"Error loading DKIM config: {e}")
		return None


def load_multi_domain_dkim(config_path: str = "config.yaml") -> Dict[str, DKIMSigner]:
	"""Load DKIM signers for all configured domains.
	
	Returns:
		Dict mapping domain name to DKIMSigner instance
	"""
	try:
		import yaml
		
		with open(config_path, 'r') as f:
			config = yaml.safe_load(f)
		
		dkim_config = config.get('dkim', {})
		
		if not dkim_config.get('enabled', False):
			logger.info("DKIM signing disabled in config")
			return {}
		
		signers = {}
		
		# Load multi-domain configuration
		domains_config = dkim_config.get('domains', [])
		for domain_conf in domains_config:
			domain = domain_conf.get('domain')
			selector = domain_conf.get('selector', 'default')
			private_key = domain_conf.get('private_key', f'certs/dkim_{selector}.pem')
			if domain:
				signer = DKIMSigner(
					domain=domain,
					selector=selector,
					private_key_path=private_key
				)
				if signer.private_key:
					signers[domain] = signer
					logger.info(f"DKIM signer loaded for {domain} (selector: {selector})")
				else:
					logger.warning(f"DKIM key not found for {domain}")
		
		# Single domain fallback
		if not signers:
			domain = dkim_config.get('domain')
			selector = dkim_config.get('selector', 'default')
			private_key = dkim_config.get('private_key', f'certs/dkim_{selector}.pem')
			if domain:
				signer = DKIMSigner(domain=domain, selector=selector, private_key_path=private_key)
				if signer.private_key:
					signers[domain] = signer
		
		return signers
		
	except Exception as e:
		logger.error(f"Error loading multi-domain DKIM config: {e}")
		return {}
