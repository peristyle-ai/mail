# Mail Server - API Documentation

## Overview

REST API for email management with JWT authentication. Supports both inbound email storage and outbound email delivery to external providers (Gmail, Outlook, etc.)

## Server Details

- **Base URL**: `http://localhost:5003`
- **API Port**: 5003
- **SMTP Port**: 2525 (for internal use)
- **Swagger UI**: `http://localhost:5003/docs`
- **Domain**: example.com.au
- **Status**: All 112 tests passing, Gmail delivery working

## Authentication

All protected endpoints require JWT token in header:
```
Authorization: Bearer <token>
```

### 1. Login to Obtain JWT Token

**Endpoint**: `POST /auth/login`

**Request**:
```bash
curl -X POST http://localhost:5003/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "the operator@example.com.au",
    "password": "not-a-real-password"
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
  "password": "not-a-real-password",
  "name": "User Name"
}
```

#### Login
**Endpoint**: `POST /auth/login`

**Request**:
```json
{
  "email": "user@example.com",
  "password": "not-a-real-password"
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

Returns all emails for authenticated user. For outbound emails, check the Sent folder.

#### Get Email
**Endpoint**: `GET /api/emails/<id>`

Get a specific email by ID.

#### Create Email (Send)
**Endpoint**: `POST /api/emails`

**Request**:
```bash
curl -X POST http://localhost:5003/api/emails \
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
curl http://localhost:5003/api/emails/123/delivery-status \
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

Multipart form data with `file` field.

#### List Attachments
**Endpoint**: `GET /api/emails/<id>/attachments`

#### Download
**Endpoint**: `GET /api/attachments/<id>`

#### Delete
**Endpoint**: `DELETE /api/attachments/<id>`

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

BASE_URL = "http://localhost:5003"
EMAIL = "the operator@example.com.au"
PASSWORD = "not-a-real-password"

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

3. **DNS Configuration** (for Gmail delivery):
   - **DKIM**: `default._domainkey.example.com.au` TXT record
   - **SPF**: `v=spf1 ip4:144.6.112.4 -all`
   - **PTR**: `144.6.112.4` → `example.com.au`

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

**Current Status**: All 112 tests passing

---

## Important Notes

1. **Port**: API runs on port 5003 (NOT 5001)
2. **Swagger UI**: Available at `http://localhost:5003/docs`
3. **Authorized User**: the operator@example.com.au (ID 268)
4. **Test Recipient**: payroll@example.com
5. **Delivery Time**: 30-60 seconds for Gmail
6. **Rate Limiting**: 30 emails/min per domain, 100/hour total
7. **Queue Processing**: Every 30 seconds
8. **Authentication**: All endpoints except /health require Bearer token

---

## Files & Locations

- **Server Code**: `/opt/py_pg_accounts/git/py_pg_email/`
- **Config**: `/opt/py_pg_accounts/git/py_pg_email/config.yaml`
- **Systemd Service**: `/opt/py_pg_accounts/git/py_pg_email/systemd/user/mail-server.service`
- **Test Scripts**: `/opt/py_pg_accounts/git/py_pg_email/scripts/`
- **API Guide**: `/opt/py_pg_accounts/git/py_pg_email/coding_agent/API_INTEGRATION_GUIDE.md`

---

## Changelog

- **2026-02-15**: Added delivery status endpoint (`GET /api/emails/{id}/delivery-status`)
- **2026-02-15**: Fixed greylist to auto-whitelist across all recipients
- **2026-02-15**: Fixed NUL character handling in email storage
- **2026-02-14**: Fixed port from 5001 to 5003
- **2026-02-14**: Added IPv4 forced delivery for Gmail
- **2026-02-14**: Added Message-ID header for Gmail compliance
- **2026-02-14**: Added DKIM signing

---

**Last Updated**: 2026-02-15
**Status**: All 112 tests passing, Gmail delivery verified
