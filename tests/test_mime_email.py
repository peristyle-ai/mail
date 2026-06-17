import pytest
import json


class TestMimeEmail:
	"""Test the MIME email endpoint for embedded images"""
	
	def test_mime_email_simple_html(self, client, auth_headers):
		"""Test sending a simple MIME email without images"""
		mime_content = '''Content-Type: multipart/related; boundary="==test=="
MIME-Version: 1.0
Subject: Test MIME Email
From: test@example.com
To: recipient@example.com

--==test==
Content-Type: text/html; charset=utf-8

<html><body><h1>Test</h1><p>This is a test.</p></body></html>
--==test==--'''
		
		response = client.post(
			'/api/emails/mime',
			headers=auth_headers,
			json={
				'to': 'recipient@example.net',
				'mime_content': mime_content
			}
		)
		
		assert response.status_code == 201
		data = response.get_json()
		assert 'id' in data
		assert data['queued'] is True
		assert data['status'] == 'pending'
	
	def test_mime_email_with_embedded_image(self, client, auth_headers):
		"""Test sending a MIME email with embedded image"""
		# Simple 1x1 transparent PNG base64 encoded
		png_data = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg=='
		
		mime_content = f'''Content-Type: multipart/related; boundary="==boundary=="
MIME-Version: 1.0
Subject: Test with Image
From: test@example.com
To: recipient@example.com

--==boundary==
Content-Type: text/html; charset=utf-8

<html>
<body>
<h1>Test Image</h1>
<img src="cid:test_image" width="100" height="100">
</body>
</html>

--==boundary==
Content-Type: image/png
Content-Transfer-Encoding: base64
Content-ID: <test_image>
Content-Disposition: inline; filename="test.png"

{png_data}

--==boundary==--'''
		
		response = client.post(
			'/api/emails/mime',
			headers=auth_headers,
			json={
				'to': 'recipient@example.net',
				'mime_content': mime_content
			}
		)
		
		assert response.status_code == 201
		data = response.get_json()
		assert 'id' in data
		assert data['queued'] is True
	
	def test_mime_email_missing_content(self, client, auth_headers):
		"""Test error when mime_content is missing"""
		response = client.post(
			'/api/emails/mime',
			headers=auth_headers,
			json={'to': 'test@example.com'}
		)
		
		assert response.status_code == 400
		data = response.get_json()
		assert 'error' in data
	
	def test_mime_email_missing_to(self, client, auth_headers):
		"""Test error when to field is missing"""
		response = client.post(
			'/api/emails/mime',
			headers=auth_headers,
			json={'mime_content': 'test content'}
		)
		
		assert response.status_code == 400
		data = response.get_json()
		assert 'error' in data
	
	def test_mime_email_unauthorized(self, client):
		"""Test that endpoint requires authentication"""
		response = client.post(
			'/api/emails/mime',
			json={'to': 'test@example.com', 'mime_content': 'test'}
		)
		
		assert response.status_code == 401
	
	def test_mime_email_multiple_images(self, client, auth_headers):
		"""Test sending a MIME email with multiple embedded images"""
		png_data = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFBQIAX8jx0gAAAABJRU5ErkJggg=='
		
		mime_content = f'''Content-Type: multipart/related; boundary="==boundary=="
MIME-Version: 1.0
Subject: Test Multiple Images
From: test@example.com
To: recipient@example.com

--==boundary==
Content-Type: text/html; charset=utf-8

<html>
<body>
<h1>Two Images</h1>
<img src="cid:image1" width="50" height="50">
<img src="cid:image2" width="50" height="50">
</body>
</html>

--==boundary==
Content-Type: image/png
Content-Transfer-Encoding: base64
Content-ID: <image1>
Content-Disposition: inline; filename="image1.png"

{png_data}

--==boundary==
Content-Type: image/png
Content-Transfer-Encoding: base64
Content-ID: <image2>
Content-Disposition: inline; filename="image2.png"

{png_data}

--==boundary==--'''
		
		response = client.post(
			'/api/emails/mime',
			headers=auth_headers,
			json={
				'to': 'recipient@example.net',
				'mime_content': mime_content
			}
		)
		
		assert response.status_code == 201
		data = response.get_json()
		assert 'id' in data
		assert data['queued'] is True
	
	def test_mime_email_invalid_mime(self, client, auth_headers):
		"""Test error handling for invalid MIME content"""
		response = client.post(
			'/api/emails/mime',
			headers=auth_headers,
			json={
				'to': 'test@example.com',
				'mime_content': ''  # Empty content is invalid
			}
		)
		
		# Empty content should fail
		assert response.status_code == 400
		data = response.get_json()
		assert 'error' in data
