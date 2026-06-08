"""
Tests for HTML email body support.
"""
import pytest
from email import message_from_string
from smtp_server.email_storage import extract_bodies


class TestExtractBodies:
	"""Tests for the extract_bodies function."""
	
	def test_multipart_with_plain_and_html(self):
		"""Test extracting both plain text and HTML from multipart email."""
		multipart_email = '''From: test@example.com
To: recipient@example.com
Subject: Test
MIME-Version: 1.0
Content-Type: multipart/alternative; boundary="boundary123"

--boundary123
Content-Type: text/plain; charset=utf-8

Plain text content
--boundary123
Content-Type: text/html; charset=utf-8

<html><body><p>HTML content</p></body></html>
--boundary123--
'''
		msg = message_from_string(multipart_email)
		plain_text, html = extract_bodies(msg)
		
		assert 'Plain text content' in plain_text
		assert '<html>' in html
		assert 'HTML content' in html
	
	def test_plain_text_only_email(self):
		"""Test extracting from plain text only email."""
		plain_email = '''From: test@example.com
To: recipient@example.com
Subject: Test
Content-Type: text/plain; charset=utf-8

Just plain text body
'''
		msg = message_from_string(plain_email)
		plain_text, html = extract_bodies(msg)
		
		assert 'Just plain text body' in plain_text
		assert html == ''
	
	def test_html_only_email(self):
		"""Test extracting from HTML only email."""
		html_email = '''From: test@example.com
To: recipient@example.com
Subject: Test
Content-Type: text/html; charset=utf-8

<html><body><p>HTML only</p></body></html>
'''
		msg = message_from_string(html_email)
		plain_text, html = extract_bodies(msg)
		
		assert plain_text == ''
		assert '<html>' in html
		assert 'HTML only' in html
	
	def test_multipart_with_attachment(self):
		"""Test that attachments are skipped and only bodies extracted."""
		multipart_with_attachment = '''From: test@example.com
To: recipient@example.com
Subject: Test
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="boundary123"

--boundary123
Content-Type: text/plain; charset=utf-8

Plain text with attachment
--boundary123
Content-Type: text/html; charset=utf-8

<html><body><p>HTML with attachment</p></body></html>
--boundary123
Content-Disposition: attachment; filename="test.txt"
Content-Type: text/plain

Attachment content
--boundary123--
'''
		msg = message_from_string(multipart_with_attachment)
		plain_text, html = extract_bodies(msg)
		
		assert 'Plain text with attachment' in plain_text
		assert 'HTML with attachment' in html
		assert 'Attachment content' not in plain_text
		assert 'Attachment content' not in html
	
	def test_medium_digest_format(self):
		"""Test extraction from Medium-style digest email."""
		medium_email = '''From: noreply@medium.com
To: user@example.com
Subject: Stories for you
MIME-Version: 1.0
Content-Type: multipart/alternative; boundary="medium_boundary"

--medium_boundary
Content-Type: text/plain; charset=utf-8

Stories for user
Author Name (https://medium.com/@author?source=...)

Article Title
5 min read

--medium_boundary
Content-Type: text/html; charset=utf-8

<html><body>
<a href="https://medium.com/@author/article-slug-abc123?source=...">
Article Title
</a>
</body></html>
--medium_boundary--
'''
		msg = message_from_string(medium_email)
		plain_text, html = extract_bodies(msg)
		
		# Article URL should be in HTML but not plain text
		assert 'article-slug-abc123' not in plain_text
		assert 'article-slug-abc123' in html


class TestHTMLFieldInAPI:
	"""Tests for the html field in API responses."""
	
	def test_format_email_response_with_html(self):
		"""Test that body_html is mapped to html in response."""
		from app.routes.emails import format_email_response
		
		email_dict = {
			'id': 1,
			'subject': 'Test',
			'body': 'Plain text',
			'body_html': '<html><body>HTML</body></html>'
		}
		result = format_email_response(email_dict)
		
		assert 'html' in result
		assert result['html'] == '<html><body>HTML</body></html>'
		assert 'body_html' not in result
	
	def test_format_email_response_without_html(self):
		"""Test that emails without HTML still work."""
		from app.routes.emails import format_email_response
		
		email_dict = {
			'id': 2,
			'subject': 'Test',
			'body': 'Plain text only'
		}
		result = format_email_response(email_dict)
		
		assert 'html' not in result
		assert result['body'] == 'Plain text only'

	def test_format_email_response_extracts_body_from_subject_prefixed_mime(self):
		"""Test raw RFC 822 messages starting with Subject are decoded for API output."""
		from app.routes.emails import format_email_response
		
		raw_email_body = '''Subject: Test MIME Email
From: sender@example.com
To: recipient@example.com
MIME-Version: 1.0
Content-Type: multipart/alternative; boundary="boundary123"

--boundary123
Content-Type: text/plain; charset=utf-8

Plain text from MIME body
--boundary123
Content-Type: text/html; charset=utf-8

<html><body><p>HTML from MIME body</p></body></html>
--boundary123--
'''
		email_dict = {
			'id': 3,
			'subject': 'Stored subject',
			'body': raw_email_body,
		}
		result = format_email_response(email_dict)
		
		assert result['body'] == 'Plain text from MIME body'
		assert result['html'] == '<html><body><p>HTML from MIME body</p></body></html>'
