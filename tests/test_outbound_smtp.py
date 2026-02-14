"""
Tests for outbound SMTP delivery module.
"""

import pytest
from unittest.mock import patch, MagicMock
import smtplib
import ssl
from email.message import EmailMessage

from smtp_server.outbound.delivery import OutboundSMTPSender


class TestOutboundSMTPSender:
	"""Tests for outbound SMTP delivery."""
	
	@patch('smtplib.SMTP')
	def test_deliver_email_success(self, mock_smtp_class):
		"""Test successful email delivery."""
		mock_server = MagicMock()
		mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
		mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)
		mock_server.has_extn.return_value = False
		
		msg = EmailMessage()
		msg['Subject'] = 'Test'
		msg['From'] = 'sender@example.com'
		msg['To'] = 'recipient@example.com'
		msg.set_content('Test body')
		
		sender = OutboundSMTPSender()
		success, message = sender.deliver_email(
			'sender@example.com',
			'recipient@example.com',
			msg,
			'mail.example.com',
			25
		)
		
		assert success is True
		assert message == "Delivered"
		mock_server.send_message.assert_called_once()
	
	@patch('smtplib.SMTP')
	def test_deliver_email_with_tls(self, mock_smtp_class):
		"""Test email delivery with STARTTLS."""
		mock_server = MagicMock()
		mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
		mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)
		mock_server.has_extn.return_value = True  # Supports STARTTLS
		
		msg = EmailMessage()
		msg['Subject'] = 'Test'
		msg['From'] = 'sender@example.com'
		msg['To'] = 'recipient@example.com'
		msg.set_content('Test body')
		
		sender = OutboundSMTPSender()
		success, message = sender.deliver_email(
			'sender@example.com',
			'recipient@example.com',
			msg,
			'mail.example.com',
			587
		)
		
		assert success is True
		mock_server.starttls.assert_called_once()
		mock_server.send_message.assert_called_once()
	
	@patch('smtplib.SMTP')
	def test_deliver_email_recipient_refused(self, mock_smtp_class):
		"""Test delivery when recipient is refused."""
		mock_server = MagicMock()
		mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
		mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)
		mock_server.has_extn.return_value = False
		mock_server.send_message.side_effect = smtplib.SMTPRecipientsRefused(
			{'recipient@example.com': (550, 'User unknown')}
		)
		
		msg = EmailMessage()
		msg['Subject'] = 'Test'
		msg['From'] = 'sender@example.com'
		msg['To'] = 'recipient@example.com'
		msg.set_content('Test body')
		
		sender = OutboundSMTPSender()
		success, message = sender.deliver_email(
			'sender@example.com',
			'recipient@example.com',
			msg,
			'mail.example.com',
			25
		)
		
		assert success is False
		assert 'Recipient refused' in message
	
	@patch('smtplib.SMTP')
	def test_deliver_email_connection_error(self, mock_smtp_class):
		"""Test delivery when connection fails."""
		mock_smtp_class.side_effect = smtplib.SMTPConnectError(
			421, "Connection refused"
		)
		
		msg = EmailMessage()
		msg['Subject'] = 'Test'
		msg['From'] = 'sender@example.com'
		msg['To'] = 'recipient@example.com'
		msg.set_content('Test body')
		
		sender = OutboundSMTPSender()
		success, message = sender.deliver_email(
			'sender@example.com',
			'recipient@example.com',
			msg,
			'mail.example.com',
			25
		)
		
		assert success is False
		assert 'Connection failed' in message
	
	@patch('smtplib.SMTP')
	def test_deliver_email_temporary_failure(self, mock_smtp_class):
		"""Test delivery with temporary failure (4xx)."""
		mock_server = MagicMock()
		mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
		mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)
		mock_server.has_extn.return_value = False
		mock_server.send_message.side_effect = smtplib.SMTPDataError(
			421, "Service not available"
		)
		
		msg = EmailMessage()
		msg['Subject'] = 'Test'
		msg['From'] = 'sender@example.com'
		msg['To'] = 'recipient@example.com'
		msg.set_content('Test body')
		
		sender = OutboundSMTPSender()
		success, message = sender.deliver_email(
			'sender@example.com',
			'recipient@example.com',
			msg,
			'mail.example.com',
			25
		)
		
		assert success is False
		assert 'Temporary failure' in message
	
	@patch('smtplib.SMTP')
	def test_deliver_email_permanent_failure(self, mock_smtp_class):
		"""Test delivery with permanent failure (5xx)."""
		mock_server = MagicMock()
		mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
		mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)
		mock_server.has_extn.return_value = False
		mock_server.send_message.side_effect = smtplib.SMTPDataError(
			550, "Message rejected"
		)
		
		msg = EmailMessage()
		msg['Subject'] = 'Test'
		msg['From'] = 'sender@example.com'
		msg['To'] = 'recipient@example.com'
		msg.set_content('Test body')
		
		sender = OutboundSMTPSender()
		success, message = sender.deliver_email(
			'sender@example.com',
			'recipient@example.com',
			msg,
			'mail.example.com',
			25
		)
		
		assert success is False
		assert 'Permanent failure' in message
	
	def test_deliver_email_message_too_large(self):
		"""Test delivery when message exceeds size limit."""
		msg = EmailMessage()
		msg['Subject'] = 'Test'
		msg['From'] = 'sender@example.com'
		msg['To'] = 'recipient@example.com'
		# Add large content to exceed 1KB limit
		msg.set_content('x' * 2000)
		
		sender = OutboundSMTPSender(max_size=1000)  # 1KB limit
		success, message = sender.deliver_email(
			'sender@example.com',
			'recipient@example.com',
			msg,
			'mail.example.com',
			25
		)
		
		assert success is False
		assert 'Message too large' in message
	
	@patch('smtplib.SMTP')
	def test_deliver_with_fallback_first_success(self, mock_smtp_class):
		"""Test fallback delivery when first server succeeds."""
		mock_server = MagicMock()
		mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
		mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)
		mock_server.has_extn.return_value = False
		
		msg = EmailMessage()
		msg['Subject'] = 'Test'
		msg['From'] = 'sender@example.com'
		msg['To'] = 'recipient@example.com'
		msg.set_content('Test body')
		
		sender = OutboundSMTPSender()
		servers = [
			('mail1.example.com', 25),
			('mail2.example.com', 25),
		]
		success, message = sender.deliver_with_fallback(
			'sender@example.com',
			'recipient@example.com',
			msg,
			servers
		)
		
		assert success is True
		assert message == "Delivered"
		# Should only call first server
		assert mock_smtp_class.call_count == 1
	
	@patch('smtplib.SMTP')
	def test_deliver_with_fallback_first_fails(self, mock_smtp_class):
		"""Test fallback delivery when first server fails."""
		mock_server1 = MagicMock()
		mock_server2 = MagicMock()
		
		# First server fails, second succeeds
		mock_smtp_class.side_effect = [
			smtplib.SMTPConnectError(421, "Connection refused"),  # First fails
			MagicMock(__enter__=MagicMock(return_value=mock_server2), 
			         __exit__=MagicMock(return_value=False),
			         has_extn=MagicMock(return_value=False),
			         send_message=MagicMock())  # Second succeeds
		]
		
		msg = EmailMessage()
		msg['Subject'] = 'Test'
		msg['From'] = 'sender@example.com'
		msg['To'] = 'recipient@example.com'
		msg.set_content('Test body')
		
		sender = OutboundSMTPSender()
		servers = [
			('mail1.example.com', 25),
			('mail2.example.com', 25),
		]
		success, message = sender.deliver_with_fallback(
			'sender@example.com',
			'recipient@example.com',
			msg,
			servers
		)
		
		assert success is True
		assert message == "Delivered"
		# Should try both servers
		assert mock_smtp_class.call_count == 2
	
	@patch('smtplib.SMTP')
	def test_deliver_with_fallback_all_fail(self, mock_smtp_class):
		"""Test fallback delivery when all servers fail."""
		mock_smtp_class.side_effect = smtplib.SMTPConnectError(
			421, "Connection refused"
		)
		
		msg = EmailMessage()
		msg['Subject'] = 'Test'
		msg['From'] = 'sender@example.com'
		msg['To'] = 'recipient@example.com'
		msg.set_content('Test body')
		
		sender = OutboundSMTPSender()
		servers = [
			('mail1.example.com', 25),
			('mail2.example.com', 25),
		]
		success, message = sender.deliver_with_fallback(
			'sender@example.com',
			'recipient@example.com',
			msg,
			servers
		)
		
		assert success is False
		assert 'All servers failed' in message
