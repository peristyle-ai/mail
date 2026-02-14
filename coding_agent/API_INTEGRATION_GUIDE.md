# Email Server API Integration Guide

## Quick Reference for Coding Agents

This guide provides all the information needed to integrate with the example.com.au email server API.

---

## Server Details

- **Server Location**: `/opt/py_pg_accounts/git/py_pg_email`
- **API Base URL**: `http://localhost:5003`
- **API Port**: 5003
- **SMTP Port**: 2525 (for internal use)
- **Domain**: example.com.au
- **Authorized User**: the operator@example.com.au
- **Test Recipient**: payroll@example.com

---

## Authentication

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

### Send Email (Primary Use Case)

**Endpoint**: `POST /api/emails`

**Request**:
```bash
curl -X POST http://localhost:5003/api/emails \
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

### Other Useful Endpoints

**List Sent Emails**:
```bash
GET /api/emails
Authorization: Bearer <token>
```

**Check Server Health**:
```bash
GET /health
```

---

## Python Integration Example

```python
import requests

BASE_URL = "http://localhost:5003"
EMAIL = "the operator@example.com.au"
PASSWORD = "not-a-real-password"
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
password_hash = generate_password_hash('not-a-real-password')
cursor.execute('UPDATE users SET password_hash = %s WHERE email = %s', (password_hash, 'the operator@example.com.au'))
conn.commit()
cursor.close()
conn.close()
print('Password updated')
"
```

### Issue: Email created but not queued

**Cause**: Email created in Inbox instead of being sent

**Check**: Ensure recipient is NOT a local user:
```bash
source venv/bin/activate
python -c "
from app.db import get_db_connection
conn = get_db_connection()
cursor = conn.cursor()
cursor.execute(\"SELECT id FROM users WHERE email = 'payroll@example.com'\")
user = cursor.fetchone()
if user:
    print(f'PROBLEM: User exists locally with ID {user[\"id\"]}')
else:
    print('OK: Recipient is external')
cursor.close()
conn.close()
"
```

### Issue: "TLS certificate verify failed"

**Status**: FIXED in latest code (server now disables TLS verification when using IP addresses)

### Issue: "Missing Message-ID header"

**Status**: FIXED in latest code (server now adds Message-ID to all outbound emails)

### Issue: "IPv6 sending guidelines"

**Status**: FIXED in latest code (server now forces IPv4 delivery)

---

## Testing Commands

### Quick Health Check
```bash
curl http://localhost:5003/health
```

### Quick Login Test
```bash
curl -X POST http://localhost:5003/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "the operator@example.com.au", "password": "not-a-real-password"}'
```

### Send Quick Test Email
```bash
# Get token
TOKEN=$(curl -s -X POST http://localhost:5003/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "the operator@example.com.au", "password": "not-a-real-password"}' | python -c "import sys,json; print(json.load(sys.stdin)['token'])")

# Send email
curl -X POST http://localhost:5003/api/emails \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"to": "payroll@example.com", "subject": "Quick Test", "body": "Test body"}'
```

---

## Important Notes

1. **User ID**: The authorized user is ID 268 (the operator@example.com.au)
2. **Test Recipient**: Always use payroll@example.com for testing
3. **Delivery Time**: Expect 30-60 seconds for delivery to Gmail
4. **Rate Limiting**: 30 emails/min per domain, 100/hour total
5. **Queue**: Emails are processed every 30 seconds
6. **Authentication**: All API endpoints (except /health) require Bearer token

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

**Last Updated**: 2026-02-14 (20:50 AEST)
**Status**: All 112 tests passing, email delivery to Gmail working
**New**: Delivery status endpoint (`GET /api/emails/{id}/delivery-status`) now implemented
