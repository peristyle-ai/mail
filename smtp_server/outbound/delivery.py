"""
Outbound SMTP Delivery Client

Connects to external mail servers and delivers emails.
"""

import smtplib
import ssl
import logging
from email.message import EmailMessage
from typing import Tuple, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class OutboundSMTPSender:
	"""SMTP client for delivering emails to external servers."""
	
	def __init__(
		self,
		timeout: int = 30,
		max_size: int = 25 * 1024 * 1024,  # 25MB
		tls_required: bool = True,
		verify_cert: bool = True
	):
		self.timeout = timeout
		self.max_size = max_size
		self.tls_required = tls_required
		self.verify_cert = verify_cert
	
	def deliver_email(
		self,
		from_address: str,
		to_address: str,
		message: EmailMessage,
		mail_server: str,
		port: int = 25
	) -> Tuple[bool, str]:
		"""
		Deliver email to remote SMTP server.
		
		Args:
			from_address: Sender email address
			to_address: Recipient email address
			message: Email message to send
			mail_server: Target SMTP server hostname/IP
			port: SMTP port (usually 25, 587, or 465)
			
		Returns:
			Tuple of (success, message)
		"""
		try:
			# Check message size
			msg_size = len(message.as_bytes())
			if msg_size > self.max_size:
				return False, f"Message too large: {msg_size} bytes (max: {self.max_size})"
			
			logger.info(f"Connecting to {mail_server}:{port} to deliver to {to_address}")
			
			# Force IPv4 by resolving to IPv4 address (avoids IPv6 PTR issues)
			import socket
			using_ip_address = False
			try:
				# Get IPv4 address only
				addr_info = socket.getaddrinfo(mail_server, port, socket.AF_INET, socket.SOCK_STREAM)
				if addr_info:
					ipv4_host = addr_info[0][4][0]
					logger.info(f"Resolved {mail_server} to IPv4: {ipv4_host}")
					using_ip_address = True  # We're using an IP, not hostname
				else:
					ipv4_host = mail_server  # Fallback to original
			except Exception as e:
				logger.warning(f"Could not resolve to IPv4: {e}, using {mail_server}")
				ipv4_host = mail_server
			
			# When using IP address, we can't verify TLS cert (it won't match the IP)
			# So disable verification in that case
			if using_ip_address:
				logger.info("Using IP address - disabling TLS certificate verification")
				verify_cert = False
			else:
				verify_cert = self.verify_cert
			
			# Create connection using IPv4
			with smtplib.SMTP(ipv4_host, port, timeout=self.timeout) as server:
				# Enable debug for troubleshooting
				server.set_debuglevel(0)
				
				# Identify ourselves
				server.ehlo_or_helo_if_needed()
				
				# Try STARTTLS on port 25 or 587
				if port in (25, 587) and server.has_extn('STARTTLS'):
					try:
						context = ssl.create_default_context()
						if not verify_cert:  # Use local variable
							context.check_hostname = False
							context.verify_mode = ssl.CERT_NONE
						server.starttls(context=context)
						server.ehlo()  # Re-identify after TLS
						logger.debug(f"STARTTLS established with {mail_server}")
					except Exception as e:
						if self.tls_required:
							return False, f"TLS required but failed: {e}"
						logger.warning(f"STARTTLS failed, continuing unencrypted: {e}")
				
				# Send email
				server.send_message(message, from_address, to_address)
				
				logger.info(f"Email delivered successfully to {mail_server} for {to_address}")
				return True, "Delivered"
				
		except smtplib.SMTPRecipientsRefused as e:
			logger.error(f"Recipient refused by {mail_server}: {e}")
			return False, f"Recipient refused: {e}"
			
		except smtplib.SMTPSenderRefused as e:
			logger.error(f"Sender refused by {mail_server}: {e}")
			return False, f"Sender refused: {e}"
			
		except smtplib.SMTPDataError as e:
			# 4xx errors are temporary, 5xx are permanent
			smtp_code = getattr(e, 'smtp_code', 0)
			if smtp_code and smtp_code >= 500:
				logger.error(f"Permanent failure from {mail_server}: {e}")
				return False, f"Permanent failure: {e}"
			else:
				logger.warning(f"Temporary failure from {mail_server}: {e}")
				return False, f"Temporary failure: {e}"
				
		except smtplib.SMTPConnectError as e:
			logger.error(f"Connection error to {mail_server}:{port}: {e}")
			return False, f"Connection failed: {e}"
			
		except smtplib.SMTPException as e:
			logger.error(f"SMTP error with {mail_server}: {e}")
			return False, f"SMTP error: {e}"
			
		except ssl.SSLError as e:
			logger.error(f"SSL/TLS error with {mail_server}: {e}")
			return False, f"TLS error: {e}"
			
		except TimeoutError:
			logger.error(f"Timeout connecting to {mail_server}:{port}")
			return False, "Connection timeout"
			
		except Exception as e:
			logger.error(f"Unexpected error delivering to {mail_server}: {e}")
			return False, f"Delivery error: {e}"
	
	def deliver_with_fallback(
		self,
		from_address: str,
		to_address: str,
		message: EmailMessage,
		mail_servers: list
	) -> Tuple[bool, str]:
		"""
		Try delivering to multiple mail servers in order.
		
		Args:
			mail_servers: List of (server, port) tuples to try
			
		Returns:
			Tuple of (success, message)
		"""
		last_error = "No servers to try"
		
		for server, port in mail_servers:
			success, msg = self.deliver_email(
				from_address, to_address, message, server, port
			)
			if success:
				return True, msg
			last_error = msg
		
		return False, f"All servers failed. Last error: {last_error}"
