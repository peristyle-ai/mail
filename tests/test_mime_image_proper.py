"""
Test script to send an email with embedded image using the MIME API.
Uses Python's email.mime modules to create properly formatted MIME messages.
"""
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
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
    
    # Check image exists
    if not IMAGE_PATH.exists():
        raise FileNotFoundError(f"Image not found: {IMAGE_PATH}")
    
    # Read image
    with open(IMAGE_PATH, 'rb') as f:
        img_data = f.read()
    print(f"✓ Read image: {IMAGE_PATH.name} ({len(img_data)} bytes)")
    
    # Create MIME message properly using email.mime modules
    # This ensures correct format for Gmail/Outlook
    msg = MIMEMultipart('related')
    msg['Subject'] = f'Test: Embedded Image - {IMAGE_PATH.stem}'
    msg['From'] = EMAIL
    msg['To'] = RECIPIENT
    
    # Create HTML part with cid: reference (NO angle brackets in HTML!)
    html_content = f'''<html>
<body style="font-family: Arial, sans-serif; padding: 20px;">
<h2>Test Email with Embedded Image</h2>
<p>This email contains an embedded image below:</p>
<div style="border: 2px solid #4CAF50; padding: 10px; margin: 20px 0; display: inline-block;">
<img src="cid:test_image_001" style="max-width: 600px; height: auto; display: block;">
</div>
<p style="color: #666;">The image above should display inline.</p>
<hr>
<p style="color: #999; font-size: 12px;">Sent via py_pg_email MIME API</p>
</body>
</html>'''
    
    # Attach HTML
    html_part = MIMEText(html_content, 'html', 'utf-8')
    msg.attach(html_part)
    print(f"✓ Attached HTML content")
    
    # Attach image with proper Content-ID (WITH angle brackets in header!)
    image_part = MIMEImage(img_data, _subtype='png')
    image_part.add_header('Content-ID', '<test_image_001>')  # Note: angle brackets here
    image_part.add_header('Content-Disposition', 'inline', filename=IMAGE_PATH.name)
    msg.attach(image_part)
    print(f"✓ Attached image with Content-ID: <test_image_001>")
    
    # Convert to string for API
    mime_content = msg.as_string()
    print(f"✓ Generated MIME content ({len(mime_content)} chars)")
    
    # Send via API
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
        print(f"\n📧 Check Gmail for: 'Test: Embedded Image - {IMAGE_PATH.stem}'")
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
        print(f"✓ Test complete! Email ID: {email_id}")
        print(f"{'='*60}")
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
