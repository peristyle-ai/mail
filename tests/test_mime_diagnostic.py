"""
Diagnostic test for MIME email with embedded image.
This validates the exact format required for Gmail inline images.
"""
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from pathlib import Path
import time

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
    raise Exception(f"Login failed: {response.status_code}")

def create_proper_mime_message():
    """
    Create a properly formatted MIME message for Gmail inline images.
    
    Key requirements:
    1. HTML reference: <img src="cid:content_id"> (NO angle brackets in HTML)
    2. Content-ID header: Content-ID: <content_id> (WITH angle brackets)
    3. Content-Disposition: inline (not attachment)
    4. Use MIMEMultipart('related') for the container
    """
    
    # Read image
    with open(IMAGE_PATH, 'rb') as f:
        img_data = f.read()
    
    # Create multipart container
    msg = MIMEMultipart('related')
    msg['Subject'] = f'✓ MIME Test: Embedded Image - {IMAGE_PATH.stem}'
    msg['From'] = EMAIL
    msg['To'] = RECIPIENT
    
    # Create HTML part with cid reference
    # IMPORTANT: No angle brackets in the src attribute!
    html_content = f'''<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: Arial, sans-serif; padding: 20px; background: #f5f5f5; }}
        .container {{ background: white; padding: 20px; border-radius: 8px; max-width: 800px; }}
        .image-box {{ border: 3px solid #4CAF50; padding: 10px; margin: 20px 0; display: inline-block; }}
        img {{ max-width: 100%; height: auto; display: block; }}
        .info {{ color: #666; font-size: 14px; margin-top: 20px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>✓ MIME Email Test with Embedded Image</h1>
        <p>This email was sent using the <code>/api/emails/mime</code> endpoint.</p>
        <div class="image-box">
            <img src="cid:test_image_001" alt="Test Image">
        </div>
        <p class="info">
            <strong>Content-ID:</strong> &lt;test_image_001&gt;<br>
            <strong>Image:</strong> {IMAGE_PATH.name}<br>
            <strong>Size:</strong> {len(img_data)} bytes
        </p>
    </div>
</body>
</html>'''
    
    # Attach HTML
    html_part = MIMEText(html_content, 'html', 'utf-8')
    msg.attach(html_part)
    
    # Create image part with proper headers
    # IMPORTANT: Content-ID must have angle brackets in the header value!
    image_part = MIMEImage(img_data, _subtype='png')
    image_part.add_header('Content-ID', '<test_image_001>')  # Angle brackets here!
    image_part.add_header('Content-Disposition', 'inline', filename=IMAGE_PATH.name)
    msg.attach(image_part)
    
    return msg

def send_and_verify():
    """Send email and verify delivery"""
    
    # Get auth token
    token = get_auth_token()
    print(f"✓ Authenticated as {EMAIL}\n")
    
    # Create MIME message
    msg = create_proper_mime_message()
    mime_content = msg.as_string()
    
    print(f"MIME Message Structure:")
    print(f"  Total size: {len(mime_content)} characters")
    print(f"  Multipart type: {msg.get_content_type()}")
    print(f"  Parts: {len(msg.get_payload())}")
    for i, part in enumerate(msg.get_payload()):
        print(f"    Part {i}: {part.get_content_type()}")
        if part.get('Content-ID'):
            print(f"      Content-ID: {part.get('Content-ID')}")
    print()
    
    # Send via API
    print(f"→ Sending to {RECIPIENT}...")
    response = requests.post(
        f"{BASE_URL}/api/emails/mime",
        headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
        json={'to': RECIPIENT, 'mime_content': mime_content}
    )
    
    if response.status_code != 201:
        print(f"✗ Failed: {response.status_code}")
        print(response.text)
        return None
    
    data = response.json()
    email_id = data['id']
    print(f"✓ Email queued (ID: {email_id})\n")
    
    # Wait and check delivery
    print("→ Checking delivery status (waiting 45 seconds)...")
    time.sleep(45)
    
    status_response = requests.get(
        f"{BASE_URL}/api/emails/{email_id}/delivery-status",
        headers={'Authorization': f'Bearer {token}'}
    )
    
    if status_response.status_code == 200:
        status_data = status_response.json()
        print(f"\nDelivery Status: {status_data['status']}")
        
        if status_data['status'] == 'sent':
            entry = status_data['queue_entries'][0]
            print(f"  ✓ Delivered to: {entry['recipient']}")
            print(f"  ✓ Delivered at: {entry['delivered_at']}")
            print(f"\n{'='*60}")
            print(f"✓ SUCCESS! Email {email_id} delivered to Gmail")
            print(f"{'='*60}")
            print(f"\nPlease check {RECIPIENT} for:")
            print(f"  Subject: '✓ MIME Test: Embedded Image - {IMAGE_PATH.stem}'")
            print(f"\nThe image should display inline in the email body.")
            return email_id
        else:
            print(f"  Status: {status_data['status']}")
            if status_data.get('logs'):
                for log in status_data['logs']:
                    print(f"    - {log['event']}: {log.get('error', 'OK')}")
    else:
        print(f"✗ Could not check delivery status: {status_response.status_code}")
    
    return email_id

if __name__ == "__main__":
    try:
        email_id = send_and_verify()
        if email_id:
            print(f"\n✓ Test complete. Email ID: {email_id}")
        else:
            print("\n✗ Test failed")
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
