# Mail Server - API Documentation

## Overview

REST API for email management with JWT authentication. Supports both inbound email storage and outbound email delivery to external providers (Gmail, Outlook, etc.)

## Server Details

- **Base URL**: `http://192.168.4.41:5003`
- **API Port**: 5003
- **SMTP Port**: 2525 (for internal use)
- **Swagger UI**: `http://192.168.4.41:5003/docs`
- **Domain**: example.com.au, example.ai, example.ai, mailrelay.com (multi-domain)
- **Status**: All tests passing, Gmail delivery working

## Authentication

All protected endpoints require JWT token in header:
```
Authorization: Bearer <token>
```

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

### Authentication

#### Register
**Endpoint**: `POST /auth/register`

**Request**:
```json
{
  "email": "user@example.com",
  "password": "password123",
  "name": "User Name"
}
```

#### Login
**Endpoint**: `POST /auth/login`

**Request**:
```json
{
  "email": "user@example.com",
  "password": "password123"
}
```

**Response**:
```json
{
  "token": "jwt_token_here",
  "user": {"id": 1, "email": "user@example.com"}
}
```

---

### Emails

#### List Emails
**Endpoint**: `GET /api/emails`

Returns all emails in the authenticated user's folders (based on folder ownership). Each user only sees emails in their own folders.

**Query Parameters**:
- `folder` (optional): Filter emails by folder name (e.g., `Inbox`, `Sent`)

**Examples**:
```bash
# Get all emails across all folders
GET /api/emails

# Get only inbox emails
GET /api/emails?folder=Inbox

# Get only sent emails
GET /api/emails?folder=Sent
```

**Response** (each email includes):
```json
{
  "id": 123,
  "subject": "Hello",
  "body": "Email body...",
  "html": "<html>...</html>",
  "sender": {"email": "sender@example.com", "name": null},
  "recipient": {"email": "recipient@example.com", "name": null},
  "folder": "Inbox",
  "folder_id": 5,
  "is_read": false,
  "is_starred": false,
  "created_at": "2026-05-15T10:00:00+10:00"
}
```

#### Get Email
**Endpoint**: `GET /api/emails/<id>`

Get a specific email by ID. Response includes `folder` field indicating which folder the email belongs to.

#### Create Email (Send)
**Endpoint**: `POST /api/emails`

**Request**:
```bash
curl -X POST http://192.168.4.41:5003/api/emails \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "to": "recipient@example.com",
    "subject": "Subject",
    "body": "Email body"
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
- Response includes `queued: true` for outbound emails
- For local recipients (same domain), a copy is placed in the recipient's Inbox automatically
- If sender and recipient are the same user, only one copy is created in Sent (no duplicate in Inbox)

#### Send Email with Embedded Images (MIME)
**Endpoint**: `POST /api/emails/mime`

Send emails with embedded images using raw MIME multipart format. Perfect for sending charts, plots, and rich HTML emails.

**Request**:
```bash
curl -X POST http://192.168.4.41:5003/api/emails/mime \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "to": "recipient@example.com",
    "mime_content": "Content-Type: multipart/related; boundary=\"==boundary==\"\nMIME-Version: 1.0\nSubject: Report with Charts\nFrom: sender@example.com\nTo: recipient@example.com\n\n--==boundary==\nContent-Type: text/html; charset=utf-8\n\n<html><body><h1>Daily Report</h1><img src=\"cid:chart1\"></body></html>\n--==boundary==\nContent-Type: image/png\nContent-Transfer-Encoding: base64\nContent-ID: <chart1>\nContent-Disposition: inline; filename=\"chart.png\"\n\niVBORw0KGgo...\n--==boundary==--"
  }'
```

**Request Body**:
- `to` (required): Recipient email address
- `mime_content` (required): Raw MIME multipart message content

**HTML Requirements**:
- Use `cid:` protocol to reference embedded images (e.g., `<img src="cid:chart1">`)
- Match the Content-ID in the MIME part exactly (e.g., `Content-ID: <chart1>`)
- Use `multipart/related` content type for the main message

**Successful Response**:
```json
{
  "id": 123,
  "queued": true,
  "status": "pending"
}
```

**Error Response**:
```json
{
  "error": "Invalid MIME content",
  "details": "Failed to parse MIME message"
}
```

**Python Example**:
```python
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
import requests

# Create MIME message
msg = MIMEMultipart('related')
msg['Subject'] = 'Daily Report'
msg['From'] = 'sender@example.com'
msg['To'] = 'recipient@example.com'

# Add HTML
html = '<html><body><img src="cid:chart1"></body></html>'
msg.attach(MIMEText(html, 'html'))

# Add image
with open('chart.png', 'rb') as f:
    img = MIMEImage(f.read())
    img.add_header('Content-ID', '<chart1>')
    img.add_header('Content-Disposition', 'inline', filename='chart.png')
    msg.attach(img)

# Send via API
response = requests.post(
    'http://192.168.4.41:5003/api/emails/mime',
    headers={'Authorization': f'Bearer {token}'},
    json={
        'to': 'recipient@example.com',
        'mime_content': msg.as_string()
    }
)
```

#### Mark as Read
**Endpoint**: `POST /api/emails/<id>/read`

#### Toggle Starred
**Endpoint**: `POST /api/emails/<id>/star`

**Response**:
```json
{
  "is_starred": true
}
```

#### Delete Email
**Endpoint**: `DELETE /api/emails/<id>`

**Response**:
```json
{
  "status": "deleted"
}
```

#### Move Email
**Endpoint**: `POST /api/emails/<id>/move`

**Request**:
```json
{
  "folder_id": 2
}
```

**Response**:
```json
{
  "status": "moved"
}
```

---

### Email Delivery Status (NEW)

**Endpoint**: `GET /api/emails/{id}/delivery-status`

Check the delivery status of an outbound email.

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
      "recipient": "user@example.com",
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
- `pending` - Email queued, waiting to be sent
- `sending` - Currently attempting delivery
- `retry` - Delivery failed, will retry later
- `failed` - Delivery failed permanently
- `not_found` - No outbound delivery record (email may have been received, not sent)

---

### Search

**Endpoint**: `GET /api/search`

Search emails with filters.

**Query Parameters**:
- `q` (string): Search query (searches in subject and body)
- `folder_id` (integer): Filter by folder ID
- `flag` (string): Filter by flag - `read`, `unread`, `starred`
- `page` (integer): Page number for pagination (default: 1)
- `limit` (integer): Results per page (default: 20)

**Example**:
```bash
GET /api/search?q=project&folder_id=1&flag=read&page=1&limit=20
Authorization: Bearer <token>
```

---

### Attachments

#### Upload
**Endpoint**: `POST /api/emails/<id>/attachments`

Upload a file attachment to an email. Uses folder-based authorization — you must own the email's folder.

**Request**: Multipart form data with `file` field.
- Maximum file size: 10MB
- Allowed types: txt, pdf, png, jpg, jpeg, gif, doc, docx, zip

#### List Attachments
**Endpoint**: `GET /api/emails/<id>/attachments`

Returns attachment metadata for an email. Uses folder-based authorization.

**Response**:
```json
[
  {
    "id": 5,
    "email_id": 2464,
    "file_name": "report.pdf",
    "content_type": "application/pdf",
    "file_size": 12345
  }
]
```

#### Download
**Endpoint**: `GET /api/attachments/<id>`

Download an attachment file. For attachments saved to disk (incoming SMTP or uploaded via API), serves the file directly. For legacy attachments with no filesystem path, extracts the file from the email's `raw_email` MIME data on-the-fly.

**Response**: Binary file download with `Content-Disposition: attachment` header.

**Error Responses**:
- `404`: Attachment not found, not authorized, or data not available in any form

#### Delete
**Endpoint**: `DELETE /api/attachments/<id>`

Delete an attachment and its file (if on filesystem). Uses folder-based authorization.

---

### Folders

**Endpoint**: `GET /api/folders`

List all folders for the authenticated user.

**Create Folder**:
```bash
POST /api/folders
Authorization: Bearer <token>
Content-Type: application/json

{
  "name": "Work"
}
```

---

### IP Blacklist Management (NEW)

Manage IP blacklist for blocking spam/abusive senders at the SMTP level.

#### List Blacklisted IPs
**Endpoint**: `GET /api/blacklist/ip`

Query Parameters:
- `source` (string): Filter by source (manual, auto_spf_fail, auto_rate_limit, dnsbl)
- `active_only` (boolean): Only show non-expired entries (default: true)
- `page` (integer): Page number (default: 1)
- `limit` (integer): Results per page (default: 20)

**Example**:
```bash
curl http://192.168.4.41:5003/api/blacklist/ip \
  -H "Authorization: Bearer <token>"
```

**Response**:
```json
{
  "blacklisted_ips": [
    {
      "id": 1,
      "ip_address": "192.168.1.100",
      "reason": "Repeated spam attempts",
      "source": "manual",
      "expires_at": null,
      "hit_count": 5,
      "created_at": "2026-02-16T10:00:00"
    }
  ],
  "total": 1,
  "page": 1,
  "limit": 20
}
```

#### Add IP to Blacklist
**Endpoint**: `POST /api/blacklist/ip`

**Request**:
```bash
curl -X POST http://192.168.4.41:5003/api/blacklist/ip \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "ip_address": "192.168.1.100",
    "reason": "Spam source",
    "source": "manual",
    "expires_at": "2026-03-01T00:00:00Z"
  }'
```

**Fields**:
- `ip_address` (required): IPv4 or IPv6 address
- `reason` (optional): Reason for blacklisting
- `source` (optional): Source type (manual, auto_spf_fail, auto_rate_limit, dnsbl)
- `expires_at` (optional): ISO 8601 datetime for temporary blocks

**Response** (201 Created):
```json
{
  "id": 1,
  "ip_address": "192.168.1.100",
  "reason": "Spam source",
  "source": "manual",
  "expires_at": "2026-03-01T00:00:00",
  "hit_count": 0,
  "created_at": "2026-02-16T10:00:00"
}
```

#### Remove IP from Blacklist (by ID)
**Endpoint**: `DELETE /api/blacklist/ip/<id>`

**Example**:
```bash
curl -X DELETE http://192.168.4.41:5003/api/blacklist/ip/1 \
  -H "Authorization: Bearer <token>"
```

**Response**:
```json
{
  "status": "removed",
  "ip_address": "192.168.1.100"
}
```

#### Remove IP from Blacklist (by Address)
**Endpoint**: `DELETE /api/blacklist/ip/address/<ip_address>`

**Example**:
```bash
curl -X DELETE http://192.168.4.41:5003/api/blacklist/ip/address/192.168.1.100 \
  -H "Authorization: Bearer <token>"
```

#### Check if IP is Blacklisted
**Endpoint**: `GET /api/blacklist/ip/check/<ip_address>`

**Example**:
```bash
curl http://192.168.4.41:5003/api/blacklist/ip/check/192.168.1.100 \
  -H "Authorization: Bearer <token>"
```

**Response** (when blacklisted):
```json
{
  "ip_address": "192.168.1.100",
  "is_blacklisted": true,
  "entry": {
    "id": 1,
    "reason": "Spam source",
    "source": "manual",
    "expires_at": null,
    "hit_count": 5
  },
  "message": "IP 192.168.1.100 is blacklisted"
}
```

**Response** (when not blacklisted):
```json
{
  "ip_address": "192.168.1.100",
  "is_blacklisted": false,
  "entry": null,
  "message": "IP 192.168.1.100 is not blacklisted"
}
```

#### Get Blacklist Statistics
**Endpoint**: `GET /api/blacklist/stats`

**Example**:
```bash
curl http://192.168.4.41:5003/api/blacklist/stats \
  -H "Authorization: Bearer <token>"
```

**Response**:
```json
{
  "total_entries": 10,
  "active_entries": 8,
  "expired_entries": 2,
  "by_source": {
    "manual": 5,
    "auto_spf_fail": 3,
    "auto_rate_limit": 2
  },
  "top_hit_ips": [
    {"ip_address": "192.168.1.100", "hit_count": 50, "reason": "Spam"}
  ]
}
```

**Notes**:
- Blacklisted IPs are blocked at the SMTP level before any processing
- Use 550 rejection code for blacklisted connections
- Hit counts track how many times an IP attempted to connect
- Supports both IPv4 and IPv6 addresses
- Expired entries are automatically ignored in checks

---

### Inbound Webhook (SMTP2GO / Cloudflare Email Workers)

**Endpoint**: `POST /inbound`

Receive inbound emails from SMTP2GO, Cloudflare Email Workers, or similar relay services. **No JWT authentication required** — this endpoint is called by external relay services, not end users.

Configure SMTP2GO or Cloudflare Email Workers to forward inbound emails to `https://mail.example.com.au/inbound` (or `http://192.168.4.41:5003/inbound` for direct access).

**Supported Content Types**:
- `application/x-www-form-urlencoded` (SMTP2GO default)
- `multipart/form-data` (when attachments or file uploads present)
- `application/json`

**Request Fields**:

| Field | Required | Fallback Fields | Description |
|-------|----------|-----------------|-------------|
| `from` | Yes | `from_address`, `sender` | Sender email address |
| `to` | Yes | `rcpt`, `recipient` | Recipient email address |
| `subject` | No | `subjects` | Email subject (max 500 chars) |
| `text` | No | `body` (JSON only) | Plain text body |
| `html` | No | — | HTML body |
| `sender_ip` | No | `srchost` | Sender's IP address |
| `mail` | No | `raw_email` | Raw MIME content (for body/attachment extraction) |

**File Upload**: MIME content can also be sent as a file upload in multipart/form-data requests.

**Base64 Auto-Decoding**: If `mail`/`raw_email` is Base64-encoded (as sent by Cloudflare Email Workers), it's automatically decoded before MIME parsing.

**MIME Body Extraction**: When `text` and `html` fields are both empty but `mail`/`raw_email` contains MIME content, the plain text and HTML body parts are extracted from the MIME automatically.

**Form-encoded Example (SMTP2GO)**:
```bash
curl -X POST http://192.168.4.41:5003/inbound \
  -d "from=user@example.com&to=the operator@example.com.au&subject=Test&text=Hello"
```

**Cloudflare Email Workers Example (raw_email field)**:
```bash
curl -X POST http://192.168.4.41:5003/inbound \
  -d "from=user@example.com&to=support@example.io&subject=Test&raw_email=$(base64 email.mime)"
```

**JSON Example**:
```bash
curl -X POST http://192.168.4.41:5003/inbound \
  -H "Content-Type: application/json" \
  -d '{"from":"user@example.com","to":"support@example.io","subject":"Test","text":"Hello","html":"<b>Hello</b>"}'
```

**Successful Response** (200):
```json
{
  "status": "received",
  "email_id": 2564
}
```

**Unknown Recipient Response** (200):
```json
{
  "status": "rejected",
  "reason": "unknown recipient"
}
```

**Blocked Sender Response** (200):
```json
{
  "status": "blocked"
}
```

**Error Responses**:
- `400`: Missing required fields, invalid email format, unsupported content type
- `403`: Invalid SMTP2GO signature (when `SMTP2GO_WEBHOOK_SECRET` is set)
- `413`: Payload exceeds 50MB limit
- `429`: Rate limit exceeded (60 requests/minute per IP)

**Security Features**:
- **Rate limiting**: 60 requests per minute per source IP
- **Email validation**: Regex validation, max 320 chars
- **Header injection prevention**: CR/LF stripped from all header fields
- **Payload size limits**: 50MB max (Flask `MAX_CONTENT_LENGTH` + Werkzeug `max_form_memory_size`), subject 500 chars, body 5MB
- **Sender blocklist**: Checked before storing; returns `{"status": "blocked"}`
- **SMTP2GO signature verification**: Set `SMTP2GO_WEBHOOK_SECRET` env var to enable HMAC-SHA256 verification of the `X-SMTP2GO-Signature` header
- **Attachment safety**: Filenames sanitized, individual attachment size limit 25MB, stored to disk with DB metadata
- **SQL injection**: All queries use parameterized inputs
- **String sanitization**: Null bytes removed from all stored content

**Notes**:
- Returns HTTP 200 for unknown/blocked recipients so relay services do not retry
- Creates sender user with `is_local=FALSE` if not found
- Extracts and saves attachments from the `mail`/`raw_email` MIME field when provided
- Base64-encoded MIME content (e.g., from Cloudflare Email Workers) is auto-decoded
- When `text`/`html` are empty, body content is extracted from the raw MIME
- Local domains served: `example.com.au`, `mailrelay.com`, `example.ai`, `example.ai`, `example.io`

---

### Health Check

**Endpoint**: `GET /health`

Check server status. No authentication required.

**Response**:
```json
{
  "status": "healthy"
}
```

---

## Python Integration Example

```python
import requests
import time

BASE_URL = "http://192.168.4.41:5003"
EMAIL = "the operator@example.com.au"
PASSWORD = "password123"

def get_auth_token():
    """Obtain JWT token for authentication"""
    response = requests.post(
        f"{BASE_URL}/auth/login",
        json={"email": EMAIL, "password": PASSWORD}
    )
    if response.status_code == 200:
        return response.json()["token"]
    raise Exception(f"Login failed: {response.status_code}")

def send_email(subject, body, to_address):
    """Send email via API"""
    token = get_auth_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    response = requests.post(
        f"{BASE_URL}/api/emails",
        headers=headers,
        json={"to": to_address, "subject": subject, "body": body}
    )
    
    if response.status_code == 201:
        data = response.json()
        print(f"✓ Email sent! ID: {data['id']}")
        return data["id"]
    raise Exception(f"Failed: {response.status_code}")

def check_delivery_status(email_id):
    """Check delivery status"""
    token = get_auth_token()
    headers = {"Authorization": f"Bearer {token}"}
    
    response = requests.get(
        f"{BASE_URL}/api/emails/{email_id}/delivery-status",
        headers=headers
    )
    
    if response.status_code == 200:
        data = response.json()
        print(f"Status: {data['status']}")
        for entry in data.get('queue_entries', []):
            print(f"  To: {entry['recipient']}")
            print(f"  Delivered: {entry.get('delivered_at', 'Not yet')}")
        return data
    print(f"Error: {response.status_code}")
    return None

# Example usage
if __name__ == "__main__":
    try:
        # Send email
        email_id = send_email(
            "Test Email",
            "This is a test",
            "user@example.com"
        )
        
        # Check delivery after 60 seconds
        time.sleep(60)
        check_delivery_status(email_id)
        
    except Exception as e:
        print(f"Error: {e}")
```

---

## Setup & Configuration

1. **Environment Setup**:
   ```bash
   cd /opt/py_pg_accounts/git/py_pg_email
   source venv/bin/activate
   ```

2. **Database**: PostgreSQL with tables for emails, users, folders, attachments, outbound queue

3. **DNS Configuration** (multi-domain DKIM):
    - **example.com.au**:
      - DKIM: `default._domainkey.example.com.au` TXT record
      - SPF: `v=spf1 ip4:144.6.112.4 -all`
      - PTR: `144.6.112.4` → `example.com.au`
    - **example.ai**:
      - DKIM: `fencemate._domainkey.example.ai` TXT record
      - SPF: `v=spf1 ip4:144.6.112.4 -all`
    - **example.ai**:
      - DKIM: `default._domainkey.example.ai` TXT record
      - SPF: `v=spf1 ip4:144.6.112.4 -all`
    - **mailrelay.com**:
      - DKIM: `protophys._domainkey.mailrelay.com` TXT record
      - SPF: `v=spf1 ip4:144.6.112.4 -all`

4. **Start Server**:
   ```bash
   systemctl --user start mail-server
   ```

---

## Debug & Verification

### Check Server Status
```bash
systemctl --user status mail-server
journalctl --user -u mail-server -n 50
```

### Verify Email Queued
```bash
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

### Check Delivery Logs
```bash
source venv/bin/activate
python -c "
import os
os.environ['DATABASE_URL'] = 'postgresql://postgres:1234@localhost:5432/mail_server'
from app.db import get_db_connection
conn = get_db_connection()
cursor = conn.cursor()
cursor.execute('SELECT email_id, event_type, remote_server FROM delivery_logs ORDER BY created_at DESC LIMIT 10')
for row in cursor.fetchall():
    print(f\"Email {row['email_id']}: {row['event_type']} via {row['remote_server'] or 'N/A'}\")
cursor.close()
conn.close()
"
```

---

## Testing

Run the test suite:
```bash
python -m pytest tests/ --ignore=tests/test_smtp_integration.py
```

**Current Status**: 146 tests passing (6 SMTP integration tests fail in test environment due to port conflict)

---

## Important Notes

1. **Port**: API runs on port 5003 (NOT 5001)
2. **Swagger UI**: Available at `http://192.168.4.41:5003/docs`
3. **Authorized Users**: the operator@example.com.au, clawbie@example.com.au, support@example.ai, the operator@example.ai, evie@example.ai, support@example.ai, the customer@example.com, customer@example.com, customer@example.com
4. **Multi-Domain**: Server handles mail for example.com.au, example.ai, example.ai, mailrelay.com
5. **Delivery Time**: 30-60 seconds for Gmail
6. **Rate Limiting**: 50 connections per domain, 100/hour total
7. **Queue Processing**: Every 30 seconds
8. **Authentication**: All endpoints except /health require Bearer token
9. **IP Blacklist**: All blacklist endpoints require Bearer token
10. **Folder Filtering**: `GET /api/emails?folder=Inbox` filters by folder name
11. **Self-Email**: When sender=recipient, only one copy in Sent (no duplicate Inbox copy)
12. **Auto Inbox Creation**: Inbox folder is auto-created for recipients who don't have one

---

## Files & Locations

- **Server Code**: `/opt/py_pg_accounts/git/py_pg_email/`
- **Config**: `/opt/py_pg_accounts/git/py_pg_email/config.yaml`
- **Systemd Service**: `/opt/py_pg_accounts/git/py_pg_email/systemd/user/mail-server.service`
- **Test Scripts**: `/opt/py_pg_accounts/git/py_pg_email/scripts/`
- **API Guide**: `/opt/py_pg_accounts/git/py_pg_email/coding_agent/API_INTEGRATION_GUIDE.md`

---

## Changelog

- **2026-05-21**: Added `POST /inbound` webhook endpoint for SMTP2GO relay; hardened with rate limiting, email validation, header injection prevention, SMTP2GO HMAC signature verification, payload size limits
- **2026-05-23**: Added Cloudflare Email Workers support (fallback field names, Base64 auto-decoding, MIME body extraction, file upload support, 50MB form memory limit)
- **2026-05-16**: Incoming SMTP attachments now saved to disk (not just metadata); inline images with Content-ID also saved as attachments; download endpoint falls back to extracting from `raw_email` for legacy attachments missing `file_path`
- **2026-05-15**: Added folder filter to `GET /api/emails?folder=Inbox`; added `folder` field to email responses; fixed self-email duplication (no Inbox copy when sender=recipient); fixed Inbox auto-creation for new recipients in outbound storage; fixed attachment column names (removed `file_data`, use `file_name`/`file_path`); attachment save errors no longer roll back email storage; folder-based authorization for attachment endpoints
- **2026-02-17**: Added MIME email endpoint (`POST /api/emails/mime`) for embedded images
- **2026-02-16**: Added IP blacklist API (`/api/blacklist/ip/*` endpoints)
- **2026-02-16**: Added blacklist checker module for SMTP-level IP blocking
- **2026-02-15**: Added delivery status endpoint (`GET /api/emails/{id}/delivery-status`)
- **2026-02-15**: Fixed greylist to auto-whitelist across all recipients
- **2026-02-15**: Fixed NUL character handling in email storage
- **2026-02-14**: Fixed port from 5001 to 5003
- **2026-02-14**: Added IPv4 forced delivery for Gmail
- **2026-02-14**: Added Message-ID header for Gmail compliance
- **2026-02-14**: Added DKIM signing

---

**Last Updated**: 2026-05-21
**Status**: All tests passing, multi-domain email delivery working
