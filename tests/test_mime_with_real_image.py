"""
Test script to send an email with embedded image using the MIME API.
This tests the /api/emails/mime endpoint with a real image file.
"""
import requests
import base64
from pathlib import Path

# Configuration
BASE_URL = "http://localhost:5003"
EMAIL = "user@example.com"
PASSWORD = "change-me-password"
RECIPIENT = "recipient@example.net"
IMAGE_PATH = Path(__file__).parent / "mime_test_image.png"

def get_auth_token():
    """Login and get JWT token"""
    response = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": EMAIL, "password": PASSWORD}
    )
    if response.status_code == 200:
        return response.json()["token"]
    raise Exception(f"Login failed: {response.status_code} - {response.text}")

def send_email_with_embedded_image():
    """Send email with embedded image using MIME format"""
    
    # Get auth token
    token = get_auth_token()
    print(f"✓ Authenticated as {EMAIL}")
    
    # Read and encode image
    if not IMAGE_PATH.exists():
        raise FileNotFoundError(f"Image not found: {IMAGE_PATH}")
    
    with open(IMAGE_PATH, 'rb') as f:
        image_data = f.read()
    
    image_b64 = base64.b64encode(image_data).decode('utf-8')
    print(f"✓ Read image: {IMAGE_PATH.name} ({len(image_data)} bytes, {len(image_b64)} base64 chars)")
    
    # Create MIME content with proper format for Gmail
    # Note: Using proper Content-Type and Content-Disposition headers
    mime_content = f'''Content-Type: multipart/related; boundary="==boundary=="
MIME-Version: 1.0
Subject: Test Email with Embedded Image - {Path(IMAGE_PATH).stem}
From: {EMAIL}
To: {RECIPIENT}

--==boundary==
Content-Type: text/html; charset=utf-8
Content-Transfer-Encoding: quoted-printable

<html>
<body style="font-family: Arial, sans-serif; padding: 20px;">
<h2>Test Email with Embedded Image</h2>
<p>This is a test email with an embedded image below:</p>
<div style="margin: 20px 0; border: 1px solid #ddd; padding: 10px;">
<img src="cid:test_image_001" style="max-width: 100%; height: auto; display: block;">
</div>
<p>The image above should display inline in your email client.</p>
<hr>
<p style="color: #666; font-size: 12px;">Sent via py_pg_email MIME API</p>
</body>
</html>

--==boundary==
Content-Type: image/png
Content-Transfer-Encoding: base64
Content-ID: <test_image_001>
Content-Disposition: inline; filename="{IMAGE_PATH.name}"

{image_b64}

--==boundary==--'''
    
    # Send request
    print(f"\n→ Sending email to {RECIPIENT}...")
    response = requests.post(
        f"{BASE_URL}/api/emails/mime",
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        },
        json={
            'to': RECIPIENT,
            'mime_content': mime_content
        }
    )
    
    print(f"\nResponse Status: {response.status_code}")
    
    if response.status_code == 201:
        data = response.json()
        print(f"✓ Email queued successfully!")
        print(f"  Email ID: {data.get('id')}")
        print(f"  Queued: {data.get('queued')}")
        print(f"  Status: {data.get('status')}")
        print(f"\n✓ Email should arrive in 30-60 seconds")
        return data.get('id')
    else:
        print(f"✗ Failed: {response.status_code}")
        try:
            error_data = response.json()
            print(f"  Error: {error_data}")
        except:
            print(f"  Response: {response.text}")
        raise Exception(f"Failed to send email: {response.status_code}")

if __name__ == "__main__":
    try:
        email_id = send_email_with_embedded_image()
        print(f"\n{'='*60}")
        print(f"Test complete! Email ID: {email_id}")
        print(f"Check {RECIPIENT} in 30-60 seconds")
        print(f"{'='*60}")
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
