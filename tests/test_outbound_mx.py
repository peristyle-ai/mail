"""
Tests for outbound MX lookup module.
"""

import pytest
from unittest.mock import patch, MagicMock
import dns.resolver
import dns.exception

from smtp_server.outbound.mx_lookup import MXLookup


class TestMXLookup:
	"""Tests for MX record lookup functionality."""
	
	def test_mx_lookup_success(self):
		"""Test successful MX record lookup."""
		with patch('smtp_server.outbound.mx_lookup.dns.resolver.resolve') as mock_resolve:
			# Mock MX records - need to mock __str__ for the exchange
			mock_rdata1 = MagicMock()
			mock_rdata1.preference = 10
			mock_exchange1 = MagicMock()
			mock_exchange1.__str__ = MagicMock(return_value='mail.example.com.')
			mock_rdata1.exchange = mock_exchange1
			
			mock_rdata2 = MagicMock()
			mock_rdata2.preference = 20
			mock_exchange2 = MagicMock()
			mock_exchange2.__str__ = MagicMock(return_value='mail2.example.com.')
			mock_rdata2.exchange = mock_exchange2
			
			mock_resolve.return_value = [mock_rdata1, mock_rdata2]
			
			mx = MXLookup()
			result = mx.get_mx_records('example.com')
			
			assert len(result) == 2
			assert result[0] == (10, 'mail.example.com')
			assert result[1] == (20, 'mail2.example.com')
			mock_resolve.assert_called_once_with('example.com', 'MX', lifetime=10)
	
	def test_mx_lookup_nxdomain(self):
		"""Test MX lookup for non-existent domain."""
		with patch('smtp_server.outbound.mx_lookup.dns.resolver.resolve') as mock_resolve:
			mock_resolve.side_effect = dns.resolver.NXDOMAIN()
			
			mx = MXLookup()
			result = mx.get_mx_records('nonexistent.invalid')
			
			assert result == []
	
	def test_mx_lookup_no_answer(self):
		"""Test MX lookup with no MX records."""
		with patch('smtp_server.outbound.mx_lookup.dns.resolver.resolve') as mock_resolve:
			mock_resolve.side_effect = dns.resolver.NoAnswer()
			
			mx = MXLookup()
			result = mx.get_mx_records('example.com')
			
			assert result == []
	
	def test_mx_lookup_timeout(self):
		"""Test MX lookup timeout."""
		with patch('smtp_server.outbound.mx_lookup.dns.resolver.resolve') as mock_resolve:
			mock_resolve.side_effect = dns.exception.Timeout()
			
			mx = MXLookup()
			result = mx.get_mx_records('example.com')
			
			assert result == []
	
	def test_a_record_lookup_success(self):
		"""Test successful A record lookup."""
		with patch('smtp_server.outbound.mx_lookup.dns.resolver.resolve') as mock_resolve:
			mock_rdata = MagicMock()
			mock_rdata.__str__ = MagicMock(return_value='192.0.2.1')
			mock_resolve.return_value = [mock_rdata]
			
			mx = MXLookup()
			result = mx.get_a_record('example.com')
			
			assert result == '192.0.2.1'
	
	def test_a_record_lookup_failure(self):
		"""Test A record lookup failure."""
		with patch('smtp_server.outbound.mx_lookup.dns.resolver.resolve') as mock_resolve:
			mock_resolve.side_effect = Exception("DNS error")
			
			mx = MXLookup()
			result = mx.get_a_record('example.com')
			
			assert result is None
	
	def test_get_mail_server_with_mx(self):
		"""Test getting mail server with MX records."""
		with patch('smtp_server.outbound.mx_lookup.dns.resolver.resolve') as mock_resolve:
			mock_rdata = MagicMock()
			mock_rdata.preference = 10
			mock_exchange = MagicMock()
			mock_exchange.__str__ = MagicMock(return_value='mail.example.com.')
			mock_rdata.exchange = mock_exchange
			mock_resolve.return_value = [mock_rdata]
			
			mx = MXLookup()
			result = mx.get_mail_server('user@example.com')
			
			assert result == ('mail.example.com', 25)
	
	def test_get_mail_server_mx_fallback_to_a(self):
		"""Test getting mail server - fallback to A record when no MX."""
		with patch('smtp_server.outbound.mx_lookup.dns.resolver.resolve') as mock_resolve:
			# First call (MX) fails
			# Second call (A) succeeds
			mock_rdata = MagicMock()
			mock_rdata.__str__ = MagicMock(return_value='192.0.2.1')
			mock_resolve.side_effect = [
				dns.resolver.NoAnswer(),  # No MX
				[mock_rdata]  # A record
			]
			
			mx = MXLookup()
			result = mx.get_mail_server('user@example.com')
			
			assert result == ('192.0.2.1', 25)
	
	def test_get_mail_server_no_records(self):
		"""Test getting mail server when no records exist."""
		with patch('smtp_server.outbound.mx_lookup.dns.resolver.resolve') as mock_resolve:
			mock_resolve.side_effect = [
				dns.resolver.NXDOMAIN(),  # No MX
				Exception("DNS error")  # No A record either
			]
			
			mx = MXLookup()
			result = mx.get_mail_server('user@nonexistent.invalid')
			
			assert result is None
	
	def test_get_mail_server_invalid_email(self):
		"""Test getting mail server for invalid email."""
		mx = MXLookup()
		result = mx.get_mail_server('not-an-email')
		
		assert result is None
	
	def test_verify_domain_exists_with_mx(self):
		"""Test domain verification with MX record."""
		with patch('smtp_server.outbound.mx_lookup.dns.resolver.resolve') as mock_resolve:
			mock_rdata = MagicMock()
			mock_rdata.preference = 10
			mock_rdata.exchange = MagicMock()
			mock_rdata.exchange.to_text.return_value = 'mail.example.com.'
			mock_resolve.return_value = [mock_rdata]
			
			mx = MXLookup()
			result = mx.verify_domain_exists('example.com')
			
			assert result is True
	
	def test_verify_domain_exists_with_a(self):
		"""Test domain verification with only A record."""
		with patch('smtp_server.outbound.mx_lookup.dns.resolver.resolve') as mock_resolve:
			# No MX, but A exists
			mock_rdata = MagicMock()
			mock_rdata.to_text.return_value = '192.0.2.1'
			mock_resolve.side_effect = [
				dns.resolver.NoAnswer(),  # No MX
				[mock_rdata]  # A record
			]
			
			mx = MXLookup()
			result = mx.verify_domain_exists('example.com')
			
			assert result is True
	
	def test_verify_domain_does_not_exist(self):
		"""Test domain verification when domain doesn't exist."""
		with patch('smtp_server.outbound.mx_lookup.dns.resolver.resolve') as mock_resolve:
			mock_resolve.side_effect = [
				dns.resolver.NXDOMAIN(),  # No MX
				Exception("No A record")  # No A either
			]
			
			mx = MXLookup()
			result = mx.verify_domain_exists('nonexistent.invalid')
			
			assert result is False
