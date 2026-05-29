"""
SMTP relay delivery client.

Uses authenticated SMTP relay delivery for SMTP2GO and other providers that
support standard SMTP AUTH.
"""

import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Tuple

logger = logging.getLogger(__name__)


class SMTP2GODelivery:
	"""SMTP AUTH relay client for SMTP2GO and similar providers."""

	def __init__(
		self,
		relay_host: str = 'mail-au.smtp2go.com',
		relay_port: int = 2525,
		username: str = None,
		password: str = None,
		timeout: int = 30,
		max_size: int = 25 * 1024 * 1024,
		verify_cert: bool = True
	):
		self.relay_host = relay_host
		self.relay_port = relay_port
		self.username = username
		self.password = password
		self.timeout = timeout
		self.max_size = max_size
		self.verify_cert = verify_cert

	def _create_context(self):
		"""Create an SSL context for relay connections."""
		context = ssl.create_default_context()
		if not self.verify_cert:
			context.check_hostname = False
			context.verify_mode = ssl.CERT_NONE
		return context

	def _login(self, server):
		"""Authenticate to the relay server."""
		if not self.username or not self.password:
			raise ValueError('SMTP relay credentials not configured')
		server.login(self.username, self.password)

	def verify_connection(self) -> Tuple[bool, str]:
		"""Verify the relay accepts a TLS connection and login."""
		try:
			context = self._create_context()
			if self.relay_port == 465:
				with smtplib.SMTP_SSL(self.relay_host, self.relay_port, timeout=self.timeout, context=context) as server:
					server.ehlo_or_helo_if_needed()
					self._login(server)
			else:
				with smtplib.SMTP(self.relay_host, self.relay_port, timeout=self.timeout) as server:
					server.ehlo_or_helo_if_needed()
					if not server.has_extn('STARTTLS'):
						return False, 'Relay server does not advertise STARTTLS'
					server.starttls(context=context)
					server.ehlo()
					self._login(server)
			return True, 'Relay credentials verified successfully'
		except Exception as e:
			logger.error(f'Relay verify failed for {self.relay_host}:{self.relay_port}: {e}')
			return False, str(e)

	def deliver(
		self,
		from_address: str,
		to_addresses,
		message: EmailMessage,
	) -> Tuple[bool, str]:
		"""Deliver an email through the configured SMTP relay."""
		if isinstance(to_addresses, str):
			to_addresses = [to_addresses]

		try:
			msg_size = len(message.as_bytes())
			if msg_size > self.max_size:
				return False, f'Message too large: {msg_size} bytes (max: {self.max_size})'

			context = self._create_context()
			logger.info(
				f'Relay delivery: {from_address} -> {to_addresses} '
				f'via {self.relay_host}:{self.relay_port}'
			)

			if self.relay_port == 465:
				with smtplib.SMTP_SSL(self.relay_host, self.relay_port, timeout=self.timeout, context=context) as server:
					server.ehlo_or_helo_if_needed()
					self._login(server)
					server.send_message(message, from_addr=from_address, to_addrs=to_addresses)
			else:
				with smtplib.SMTP(self.relay_host, self.relay_port, timeout=self.timeout) as server:
					server.ehlo_or_helo_if_needed()
					if not server.has_extn('STARTTLS'):
						return False, 'Relay server does not advertise STARTTLS'
					server.starttls(context=context)
					server.ehlo()
					self._login(server)
					server.send_message(message, from_addr=from_address, to_addrs=to_addresses)

			return True, 'Delivered via relay'
		except smtplib.SMTPAuthenticationError as e:
			logger.error(f'Relay authentication failed: {e}')
			return False, f'Authentication failed: {e}'
		except smtplib.SMTPRecipientsRefused as e:
			logger.error(f'Relay recipient refused: {e}')
			return False, f'Recipient refused: {e}'
		except smtplib.SMTPSenderRefused as e:
			logger.error(f'Relay sender refused: {e}')
			return False, f'Sender refused: {e}'
		except smtplib.SMTPException as e:
			logger.error(f'Relay SMTP error: {e}')
			return False, f'SMTP error: {e}'
		except ssl.SSLError as e:
			logger.error(f'Relay TLS error: {e}')
			return False, f'TLS error: {e}'
		except Exception as e:
			logger.error(f'Relay delivery failed: {e}')
			return False, str(e)
