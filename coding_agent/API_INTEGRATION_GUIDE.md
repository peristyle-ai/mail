# Email Server API Integration Guide

## Quick Reference for Coding Agents

This guide provides all the information needed to integrate with the example.com.au email server API.

---

## Server Details

- **Server Location**: `/opt/py_pg_accounts/git/py_pg_email`
- **API Base URL**: `http://192.168.4.41:5003`
- **API Port**: 5003
- **SMTP Port**: 2525 (for internal use)
- **Host IP**: 192.168.4.41 (set in .env HOST variable)
- **Domain**: example.com.au, example.ai, example.ai, mailrelay.com (multi-domain)
- **Authorized Users**: 
  - the operator@example.com.au (password123)
  - clawbie@example.com.au (password123)
  - support@example.ai
  - the operator@example.ai
  - evie@example.ai
  - support@example.ai
  - the customer@example.com
  - customer@example.com
  - customer@example.com
- **Test Recipient**: payroll@example.com

---

## Authentication

### 1. Login to Obtain JWT Token

**Endpoint**: `POST /auth/login`

**Request**:
```bash
curl -X POST http://192.168.4.41:5003/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "the operator@example.com.au",
    "password": "password123"
  }'
```

**Successful Response**:
```json
{
  "token": "eyJhbGciOiJIUzI1NiIs...",
  "user": {
    "id": 268,
    "email": "the operator@example.com.au"
  }
}
```

**Token Validity**: 24 hours

### 2. Use Token in Subsequent Requests

Include the token in the Authorization header:
```
Authorization: Bearer <token>
```

---

## API Endpoints

### Send Email (Primary Use Case)

**Endpoint**: `POST /api/emails`

**Request**:
```bash
curl -X POST http://192.168.4.41:5003/api/emails \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "to": "payroll@example.com",
    "subject": "Test Email",
    "body": "Email body content here"
  }'
```

**Successful Response**:
```json
{
  "id": 123,
  "queued": true
}
```

**Notes**:
- Emails to external addresses (like gmail.com) are automatically queued for outbound delivery
- The email will be DKIM signed before delivery
- Delivery typically takes 30-60 seconds

### Check Email Delivery Status

**Endpoint**: `GET /api/emails/{id}/delivery-status`

**Description**: Check the delivery status of an outbound email

**Request**:
```bash
curl http://192.168.4.41:5003/api/emails/123/delivery-status \
  -H "Authorization: Bearer <token>"
```

**Successful Response** (for sent email):
```json
{
  "email_id": 123,
  "status": "sent",
  "queue_entries": [
    {
      "recipient": "payroll@example.com",
      "status": "sent",
      "attempts": 1,
      "last_attempt": "2026-02-14T20:20:03.422443+10:00",
      "delivered_at": "2026-02-14T20:20:06.771581+10:00",
      "error": null
    }
  ],
  "logs": [
    {
      "event": "attempt",
      "smtp_response": null,
      "error": null,
      "remote_server": "gmail-smtp-in.l.google.com:25",
      "timestamp": "2026-02-14T20:20:03.422443+10:00"
    },
    {
      "event": "success",
      "smtp_response": null,
      "error": null,
      "remote_server": "gmail-smtp-in.l.google.com",
      "timestamp": "2026-02-14T20:20:06.781307+10:00"
    }
  ]
}
```

**Status Values**:
- `sent` - Email successfully delivered

### Send Email with Embedded Images (MIME)

**Endpoint**: `POST /api/emails/mime`

**Description**: Send emails with embedded images using raw MIME multipart format. Perfect for charts, plots, and rich HTML emails.

**IMPORTANT**: You MUST use Python's `email.mime` modules to create the MIME content. Do NOT construct it manually as a string - it will not work correctly!

**Python Example with Embedded Image** (EXACTLY follow this pattern):
```python
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
import requests

def send_email_with_image(image_path, html_content, to_address):
    """
    Send email with embedded images using the MIME endpoint.
    
    Args:
        image_path: Path to the image file (PNG, JPG, etc.)
        html_content: HTML with <img src="cid:CONTENT_ID"> tags
        to_address: Recipient email
    """
    token = get_auth_token()
    
    # CRITICAL: Use MIMEMultipart('related') for inline images
    msg = MIMEMultipart('related')
    msg['Subject'] = 'Report with Chart'
    msg['From'] = 'the operator@example.com.au'  # Must be your registered email
    msg['To'] = to_address
    
    # Attach HTML - use MIMEText, NOT raw string
    html_part = MIMEText(html_content, 'html', 'utf-8')
    msg.attach(html_part)
    
    # Attach image - CRITICAL: Must use _subtype parameter!
    with open(image_path, 'rb') as f:
        img_data = f.read()
    
    # Determine subtype from file extension
    subtype = image_path.split('.')[-1].lower()  # 'png', 'jpg', 'jpeg', 'gif'
    image_part = MIMEImage(img_data, _subtype=subtype)
    
    # CRITICAL: Content-ID must have angle brackets < >
    image_part.add_header('Content-ID', '<chart1>')  # Match the cid: in HTML
    image_part.add_header('Content-Disposition', 'inline', filename=image_path)
    msg.attach(image_part)
    
    # Send via API - use mime_content = msg.as_string()
    response = requests.post(
        'http://192.168.4.41:5003/api/emails/mime',
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        },
        json={
            'to': to_address,
            'mime_content': msg.as_string()  # CRITICAL: Use as_string(), not as_bytes()
        }
    )
    
    if response.status_code == 201:
        return response.json()['id']
    else:
        raise Exception(f"Failed: {response.status_code} - {response.text}")

# Complete working example
if __name__ == "__main__":
    # Step 1: Get token
    token = get_auth_token()
    
    # Step 2: Prepare image
    image_path = "chart.png"
    
    # Step 3: Create HTML with cid: reference (NO angle brackets!)
    # The cid: value must match the Content-ID header (minus the < >)
    html_content = '''<html>
<body>
<h1>Daily Report</h1>
<p>Here is your chart:</p>
<img src="cid:chart1" alt="Chart" style="max-width: 800px;">
</body>
</html>'''
    
    # Step 4: Send
    email_id = send_email_with_image(image_path, html_content, 'payroll@example.com')
    print(f"Email sent! ID: {email_id}")
```

**Common Mistakes to Avoid**:

1. **❌ DON'T construct MIME manually as a string**
   ```python
   # WRONG - will not work!
   mime_content = "Content-Type: multipart/related...\n<img src="cid:chart">..."
   ```

2. **❌ DON'T use `msg.as_bytes()`**
   ```python
   # WRONG
   json={'mime_content': msg.as_bytes()}
   
   # CORRECT
   json={'mime_content': msg.as_string()}
   ```

3. **❌ DON'T forget `_subtype` for images**
   ```python
   # WRONG
   image_part = MIMEImage(img_data)  # Will fail!
   
   # CORRECT  
   image_part = MIMEImage(img_data, _subtype='png')
   ```

4. **❌ DON'T use wrong cid format in HTML**
   ```python
   # WRONG
   <img src="<chart1>">     # Has angle brackets
   <img src="chart1">       # Missing cid: prefix
   
   # CORRECT
   <img src="cid:chart1">   # No angle brackets, has cid: prefix
   ```

5. **❌ DON'T forget angle brackets in Content-ID header**
   ```python
   # WRONG
   image_part.add_header('Content-ID', 'chart1')  # No brackets!
   
   # CORRECT
   image_part.add_header('Content-ID', '<chart1>')  # With brackets!
   ```

**Multiple Images Example**:
```python
# For multiple images, use unique Content-IDs
msg = MIMEMultipart('related')
msg['Subject'] = 'Report with Multiple Charts'
msg['From'] = 'the operator@example.com.au'
msg['To'] = to_address

# HTML with multiple cid references
html = '''<html>
<body>
<img src="cid:chart1">
<img src="cid:chart2">
</body>
</html>'''
msg.attach(MIMEText(html, 'html', 'utf-8'))

# First image
with open('chart1.png', 'rb') as f:
    img1 = MIMEImage(f.read(), _subtype='png')
    img1.add_header('Content-ID', '<chart1>')
    msg.attach(img1)

# Second image  
with open('chart2.png', 'rb') as f:
    img2 = MIMEImage(f.read(), _subtype='png')
    img2.add_header('Content-ID', '<chart2>')
    msg.attach(img2)

# Send
requests.post(url, json={'to': to, 'mime_content': msg.as_string()})
```

**Verify Attachments**: After sending, check attachments:
```python
# List attachments for a sent email
response = requests.get(f"{BASE_URL}/api/emails/{email_id}/attachments", headers=headers)
attachments = response.json()
# Returns: [{'id': 6, 'file_name': 'test_document.pdf', 'content_type': 'application/pdf', 'file_size': 44, ...}]
```

**Note**: Incoming SMTP attachments are now saved to disk with their binary data. The `file_path` column in the `attachments` table stores the filesystem path. For legacy attachments that were stored as metadata only (no `file_path`), the download endpoint (`GET /api/attachments/<id>`) automatically extracts the file from the email's `raw_email` MIME data. Inline images (Content-Disposition: inline with Content-ID) are also saved as downloadable attachments.

**Response**: Same as regular send endpoint
- `pending` - Email queued, waiting to be sent
- `sending` - Currently attempting delivery
- `retry` - Delivery failed, will retry later
- `failed` - Delivery failed permanently
- `not_found` - No outbound delivery record (email may have been received, not sent)

**Python Example**:
```python
def check_delivery_status(email_id):
    token = get_auth_token()
    headers = {"Authorization": f"Bearer {token}"}
    
    response = requests.get(
        f"{BASE_URL}/api/emails/{email_id}/delivery-status",
        headers=headers
    )
    
    if response.status_code == 200:
        data = response.json()
        print(f"Status: {data['status']}")
        
        for entry in data['queue_entries']:
            print(f"To: {entry['recipient']}")
            print(f"Status: {entry['status']}")
            print(f"Delivered: {entry['delivered_at']}")
            if entry['error']:
                print(f"Error: {entry['error']}")
        
        return data
    else:
        print(f"Error: {response.status_code}")
        return None
```

### List Received Emails (with HTML)

**Endpoint**: `GET /api/emails`

**Description**: List all emails for the authenticated user. Each email includes sender/recipient email addresses, optional HTML body, and folder name.

**Query Parameters**:
- `folder` (optional): Filter by folder name (e.g., `Inbox`, `Sent`)

**Examples**:
```bash
# Get all emails across all folders
curl http://192.168.4.41:5003/api/emails \
  -H "Authorization: Bearer <token>"

# Get only inbox emails
curl "http://192.168.4.41:5003/api/emails?folder=Inbox" \
  -H "Authorization: Bearer <token>"

# Get only sent emails
curl "http://192.168.4.41:5003/api/emails?folder=Sent" \
  -H "Authorization: Bearer <token>"
```

**Response** (each email includes):
```json
{
  "id": 760,
  "subject": "The Microsoft-OpenAI Divorce Is Official",
  "body": "Plain text version...",
  "html": "<!DOCTYPE html><html><body>HTML version...</body></html>",
  "sender": {"email": "noreply@medium.com", "name": null},
  "recipient": {"email": "the operator@example.com.au", "name": null},
  "folder": "Inbox",
  "folder_id": 49,
  "is_read": false,
  "is_starred": false,
  "created_at": "2026-03-09T01:30:43+10:00"
}
```

**Notes**:
- Email visibility is based on folder ownership. Users can only see/access emails in folders they own.
- The `folder` field indicates which folder the email belongs to (`Inbox`, `Sent`, etc.).
- When a user sends an email to themselves (sender = recipient), only one copy is created in the Sent folder (no duplicate in Inbox).

**Get Single Email** (includes folder name):
```bash
curl http://192.168.4.41:5003/api/emails/760 \
  -H "Authorization: Bearer <token>"
```

**Search Emails**:
```bash
curl "http://192.168.4.41:5003/api/search?q=keyword&folder_id=1&flag=unread" \
  -H "Authorization: Bearer <token>"
```

### Delete Email

**Endpoint**: `DELETE /api/emails/{id}`

**Description**: Delete an email. Users can only delete emails in their own folders.

**Request**:
```bash
curl -X DELETE http://192.168.4.41:5003/api/emails/760 \
  -H "Authorization: Bearer <token>"
```

**Response**:
```json
{
  "status": "deleted"
}
```

**Note**: Users can only delete emails in folders they own (based on folder ownership).

### Other Useful Endpoints

**Check Server Health**:
```bash
GET /health
```

### IP Blacklist Management

**List Blacklisted IPs**:
```bash
GET /api/blacklist/ip
Authorization: Bearer <token>
```

Query Parameters:
- `source`: Filter by source (manual, auto_spf_fail, auto_rate_limit, dnsbl)
- `active_only`: Only show non-expired entries (default: true)
- `page`: Page number (default: 1)
- `limit`: Results per page (default: 20)

**Add IP to Blacklist**:
```bash
POST /api/blacklist/ip
Authorization: Bearer <token>
Content-Type: application/json

{
  "ip_address": "192.168.1.100",
  "reason": "Spam source",
  "source": "manual",
  "expires_at": "2026-03-01T00:00:00Z"  // Optional, for temporary blocks
}
```

**Remove IP from Blacklist (by ID)**:
```bash
DELETE /api/blacklist/ip/<id>
Authorization: Bearer <token>
```

**Remove IP from Blacklist (by Address)**:
```bash
DELETE /api/blacklist/ip/address/<ip_address>
Authorization: Bearer <token>
```

**Check if IP is Blacklisted**:
```bash
GET /api/blacklist/ip/check/<ip_address>
Authorization: Bearer <token>
```

**Get Blacklist Statistics**:
```bash
GET /api/blacklist/stats
Authorization: Bearer <token>
```

### Sender Blocklist Management

Block specific email addresses or entire domains at the SMTP level. Blocked senders are rejected before email storage.

**List Blocked Senders**:
```bash
GET /api/blacklist/sender?page=1&limit=50
Authorization: Bearer <token>
```

**Response**:
```json
{
  "entries": [
    {
      "id": 1,
      "email": "spam@example.com",
      "domain": null,
      "source": "manual",
      "blocked_at": "2026-02-28T10:00:00+10:00",
      "blocked_by": 268,
      "notes": "Spam sender"
    }
  ],
  "total": 5,
  "page": 1
}
```

**Block a Specific Email**:
```bash
POST /api/blacklist/sender
Authorization: Bearer <token>
Content-Type: application/json

{
  "email": "spam@spammer.com",
  "notes": "Spam sender"
}
```

**Block an Entire Domain**:
```bash
POST /api/blacklist/sender
Authorization: Bearer <token>
Content-Type: application/json

{
  "domain": "spamdomain.com",
  "notes": "Spam domain - blocks all emails from this domain"
}
```

**Unblock a Sender**:
```bash
DELETE /api/blacklist/sender/<block_id>
Authorization: Bearer <token>
```

**Check if Sender is Blocked**:
```bash
curl "http://192.168.4.41:5003/api/blacklist/sender/check?email=test@spamdomain.com" \
  -H "Authorization: Bearer <token>"
```

**Response**:
```json
{
  "blocked": true,
  "email": "test@spamdomain.com",
  "domain": "spamdomain.com",
  "block_type": "domain",
  "entry": {
    "id": 1,
    "domain": "spamdomain.com",
    "source": "manual",
    "notes": "Spam domain"
  }
}
```

---

## Python Integration Example

```python
import requests

BASE_URL = "http://192.168.4.41:5003"
EMAIL = "the operator@example.com.au"
PASSWORD = "password123"
RECIPIENT = "payroll@example.com"

def get_auth_token():
    """Obtain JWT token for authentication"""
    response = requests.post(
        f"{BASE_URL}/auth/login",
        json={
            "email": EMAIL,
            "password": PASSWORD
        }
    )
    if response.status_code == 200:
        return response.json()["token"]
    else:
        raise Exception(f"Login failed: {response.status_code}")

def send_email(subject, body, to_address=RECIPIENT):
    """Send email via API"""
    token = get_auth_token()
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    response = requests.post(
        f"{BASE_URL}/api/emails",
        headers=headers,
        json={
            "to": to_address,
            "subject": subject,
            "body": body
        }
    )
    
    if response.status_code == 201:
        data = response.json()
        print(f"✓ Email sent successfully! ID: {data['id']}")
        return data["id"]
    else:
        raise Exception(f"Failed to send email: {response.status_code} - {response.text}")

def check_delivery_status(email_id):
    """Check delivery status of an email"""
    token = get_auth_token()
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    response = requests.get(
        f"{BASE_URL}/api/emails/{email_id}/delivery-status",
        headers=headers
    )
    
    if response.status_code == 200:
        data = response.json()
        status = data['status']
        
        print(f"\nDelivery Status: {status}")
        
        if status == 'sent':
            for entry in data['queue_entries']:
                print(f"✓ Delivered to: {entry['recipient']}")
                print(f"  Time: {entry['delivered_at']}")
        elif status == 'pending':
            print("⏳ Email queued, waiting to be sent...")
        elif status == 'retry':
            print("🔄 Delivery failed, will retry...")
            for entry in data['queue_entries']:
                if entry['error']:
                    print(f"  Error: {entry['error']}")
        elif status == 'failed':
            print("❌ Delivery failed permanently")
            for entry in data['queue_entries']:
                if entry['error']:
                    print(f"  Error: {entry['error']}")
        elif status == 'not_found':
            print("ℹ️  No delivery record (email may have been received, not sent)")
        
        return data
    else:
        print(f"Error checking status: {response.status_code}")
        return None

# Example usage
if __name__ == "__main__":
    try:
        # Send email
        email_id = send_email(
            subject="Test from coding agent",
            body="This is a test email sent via the API"
        )
        print(f"Email {email_id} queued for delivery to {RECIPIENT}")
        
        # Wait and check delivery status
        print("\nWaiting 60 seconds for delivery...")
        import time
        time.sleep(60)
        
        # Check delivery status
        check_delivery_status(email_id)
        
    except Exception as e:
        print(f"Error: {e}")
```

---

## Debug & Verification Steps

### 1. Check Server is Running

```bash
systemctl --user status mail-server
```

Expected: `Active: active (running)`

### 2. Check Server Logs

```bash
# View recent logs
journalctl --user -u mail-server -n 50

# Follow logs in real-time
journalctl --user -u mail-server -f
```

### 3. Verify Email Queued

```bash
# Check outbound queue
source venv/bin/activate
python -c "
import os
os.environ['DATABASE_URL'] = 'postgresql://postgres:1234@localhost:5432/mail_server'
from app.db import get_db_connection
conn = get_db_connection()
cursor = conn.cursor()
cursor.execute('SELECT email_id, recipient_email, status FROM outbound_queue ORDER BY created_at DESC LIMIT 5')
for row in cursor.fetchall():
    print(f\"Email {row['email_id']} -> {row['recipient_email']}: {row['status']}\")
cursor.close()
conn.close()
"
```

### 4. Check Delivery Status

```bash
# Check delivery logs
source venv/bin/activate
python -c "
import os
os.environ['DATABASE_URL'] = 'postgresql://postgres:1234@localhost:5432/mail_server'
from app.db import get_db_connection
conn = get_db_connection()
cursor = conn.cursor()
cursor.execute('SELECT email_id, event_type, remote_server, error_message FROM delivery_logs ORDER BY created_at DESC LIMIT 10')
for row in cursor.fetchall():
    print(f\"Email {row['email_id']}: {row['event_type']} via {row['remote_server'] or 'N/A'}\")
    if row['error_message']:
        print(f\"  Error: {row['error_message'][:100]}\")
cursor.close()
conn.close()
"
```

### 5. Test SMTP Connection (Alternative)

```bash
# Send test via SMTP port 2525
source venv/bin/activate
python scripts/send_test_email.py \
  --to payroll@example.com \
  --subject "SMTP Test" \
  --body "Testing SMTP delivery"
```

### 6. Check DNS Configuration

```bash
# Verify DKIM
dig TXT default._domainkey.example.com.au

# Verify SPF
dig TXT example.com.au

# Verify Reverse DNS
dig -x 144.6.112.4
```

---

## Common Issues & Solutions

### Issue: "Connection refused" on port 5003

**Solution**: Server may not be running
```bash
systemctl --user start mail-server
```

### Issue: "Invalid credentials" on login

**Solution**: Check password or reset it
```bash
source venv/bin/activate
python -c "
from werkzeug.security import generate_password_hash
from app.db import get_db_connection
conn = get_db_connection()
cursor = conn.cursor()
password_hash = generate_password_hash('password123')
cursor.execute('UPDATE users SET password_hash = %s WHERE email = %s', (password_hash, 'the operator@example.com.au'))
conn.commit()
cursor.close()
conn.close()
print('Password updated')
"
```

### Issue: Email created but not queued

**Cause**: Recipient is treated as local user (is_local = TRUE in users table)

**Check**: Verify recipient is not a local user:
```bash
source venv/bin/activate
python -c "
from app.db import get_db_connection
conn = get_db_connection()
cursor = conn.cursor()
cursor.execute(\"SELECT id, is_local FROM users WHERE email = 'payroll@example.com'\")
user = cursor.fetchone()
if user and user['is_local']:
    print(f'PROBLEM: User exists locally with is_local=TRUE (ID {user[\"id\"]})')
elif user:
    print(f'OK: User is external (is_local=FALSE, ID {user[\"id\"]})')
else:
    print('OK: Recipient is external (no local user)')
cursor.close()
conn.close()
"
```

**Fix**: Set is_local = FALSE for external users:
```sql
UPDATE users SET is_local = FALSE WHERE email = 'payroll@example.com';
```

### Issue: External emails not in outbound queue

**Cause**: Recipients marked as local users (is_local = TRUE)

**Status**: FIXED - emails to external users (is_local = FALSE) are now properly queued

---

## Testing Commands

### Quick Health Check
```bash
curl http://192.168.4.41:5003/health
```

### Quick Login Test
```bash
curl -X POST http://192.168.4.41:5003/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "the operator@example.com.au", "password": "password123"}'
```

### Send Quick Test Email
```bash
# Get token
TOKEN=$(curl -s -X POST http://192.168.4.41:5003/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "the operator@example.com.au", "password": "password123"}' | python -c "import sys,json; print(json.load(sys.stdin)['token'])")

# Send email
curl -X POST http://192.168.4.41:5003/api/emails \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"to": "payroll@example.com", "subject": "Quick Test", "body": "Test body"}'
```

---

## Important Notes

1. **User IDs**: 
   - the operator@example.com.au is ID 268
   - clawbie@example.com.au is ID 356
2. **Test Recipient**: Always use payroll@example.com for testing
3. **Delivery Time**: Expect 30-60 seconds for delivery to Gmail
4. **Rate Limiting**: 50 connections per domain, 100/hour total
5. **Queue**: Emails are processed every 30 seconds
6. **Authentication**: All API endpoints (except /health) require Bearer token
7. **IP Blacklist**: Use `/api/blacklist/ip/*` endpoints to manage blocked IPs
8. **Sender Blocklist**: Use `/api/blacklist/sender/*` endpoints to block email addresses or domains
9. **HTML Emails**: Received emails include `html` field for HTML content
10. **Raw Email Storage**: New emails store raw MIME content for future extraction
11. **Email Addresses**: API returns `sender` and `recipient` as objects `{email, name}` instead of flat fields
12. **is_local Column**: Users table has `is_local` boolean - TRUE for local users, FALSE for external senders
13. **Server Host**: Must set HOST in .env file (e.g., HOST=192.168.4.41)
14. **Folder Filtering**: Use `GET /api/emails?folder=Inbox` to filter by folder; responses include `folder` field
15. **Self-Email**: When sender=recipient, only Sent copy is created (no duplicate Inbox copy)
16. **Multi-Domain DKIM**: Each domain has its own DKIM selector (default, fencemate, protophys)
17. **Auto Inbox Creation**: Inbox folder is auto-created for local recipients who don't have one
18. **Attachments**: Incoming SMTP attachments are saved to disk with their binary data (attachments directory); inline images with Content-ID are also captured; legacy attachments without `file_path` fall back to extraction from `raw_email`; API uploads saved to filesystem
19. **Attachment Auth**: Folder-based authorization for all attachment endpoints (not sender_id)

---

## Files & Locations

- **Server Code**: `/opt/py_pg_accounts/git/py_pg_email/`
- **Config**: `/opt/py_pg_accounts/git/py_pg_email/config.yaml`
- **Systemd Service**: `/opt/py_pg_accounts/git/py_pg_email/systemd/user/mail-server.service`
- **Test Scripts**: `/opt/py_pg_accounts/git/py_pg_email/scripts/`
- **Logs**: `journalctl --user -u mail-server`

---

## Contact & Help

If issues persist:
1. Check server logs: `journalctl --user -u mail-server -n 100`
2. Verify tests pass: `python -m pytest tests/ --ignore=tests/test_smtp_integration.py`
3. Check database connectivity
4. Verify all DNS records (DKIM, SPF, PTR) are correct

---

**Last Updated**: 2026-05-16
**Status**: 146 tests passing, multi-domain email delivery working
**Features**:
- MIME email endpoint for embedded images (`POST /api/emails/mime`)
- IP Blacklist API endpoints (`/api/blacklist/ip/*`)
- Sender Blocklist API endpoints (`/api/blacklist/sender/*`) - block emails/domains at SMTP level
- HTML email body in received emails (`html` field in API responses)
- Raw email storage for future extraction (`raw_email` field)
- Sender/recipient as objects in API (`sender` and `recipient` fields with `{email, name}`)
- is_local column for users - distinguishes local vs external users
- recipient_id properly set on sent emails
- outbound queue properly populated for external recipients
- Attachment listing works for MIME emails (`/api/emails/{id}/attachments`)
- Folder filtering on email list (`GET /api/emails?folder=Inbox`)
- Folder name in email responses (`folder` field)
- Self-email deduplication (no Inbox copy when sender=recipient)
- Auto Inbox folder creation for new local recipients
- Multi-domain DKIM signing (example.com.au, example.ai, example.ai, mailrelay.com)
- Major provider greylist whitelist stored in PostgreSQL
- SMTP rate limit: 50 connections per domain
- Attachment column fix: `file_name` and `file_path` (no `file_data`/`user_id`/`filename`)
- Attachment savepoints: failed attachments don't roll back email storage
- Incoming attachments saved to disk with binary data (not just metadata)
- Inline images (Content-ID) also saved as downloadable attachments
- Legacy attachment download: falls back to extracting from `raw_email` when `file_path` is NULL
