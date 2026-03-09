# Sender Blocklist Implementation - Integration Guide

## Implementation Status: COMPLETE

## Overview

The sender blocklist allows blocking specific email addresses or entire domains at the SMTP level. Blocked senders are rejected before emails are stored in the database.

## Architecture

```
User blocks sender → Client calls API → Server stores in DB → SMTP rejects future emails
                       ↓
Client displays blocklist → API returns entries ← Server DB
```

## Database Changes

### New Table: `sender_blocklist`

```sql
CREATE TABLE sender_blocklist (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255),              -- Specific email to block
    domain VARCHAR(255),             -- Domain to block (blocks all)
    source VARCHAR(50) DEFAULT 'manual',
    blocked_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    blocked_by INTEGER REFERENCES users(id),
    notes TEXT,
    CONSTRAINT check_block_target CHECK (email IS NOT NULL OR domain IS NOT NULL)
);
```

## API Endpoints

### 1. List Blocked Senders

```
GET /api/blacklist/sender?page=1&limit=50
Authorization: Bearer <token>

Response:
{
  "entries": [
    {
      "id": 1,
      "email": "spam@example.com",
      "domain": null,
      "source": "manual",
      "blocked_at": "2026-02-27T21:00:00+10:00",
      "blocked_by": 268,
      "notes": "Spam sender"
    }
  ],
  "total": 5,
  "page": 1
}
```

### 2. Block a Sender

```
POST /api/blacklist/sender
Authorization: Bearer <token>
Content-Type: application/json

Block specific email:
{
  "email": "spam@spammer.com",
  "notes": "Spam sender"
}

Block entire domain:
{
  "domain": "spamdomain.com",
  "notes": "Spam domain"
}

Response:
{
  "success": true,
  "id": 1
}
```

### 3. Unblock a Sender

```
DELETE /api/blacklist/sender/<block_id>
Authorization: Bearer <token>

Response:
{
  "success": true
}
```

### 4. Check if Sender is Blocked

```
GET /api/blacklist/sender/check?email=test@spamdomain.com
Authorization: Bearer <token>

Response:
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

## SMTP Integration

When an email is received, the SMTP handler checks:

1. **Sender blocklist** - Reject if email or domain is blocked
2. **IP blocklist** - Reject if sender IP is blocked
3. **Rate limiting** - Reject if rate limits exceeded
4. **SPF validation** - Reject if SPF fails
5. **Greylisting** - Delay unknown senders

Blocked senders receive: `550 Sender blocked`

## Files Changed

| File | Change |
|------|--------|
| `db/schema.sql` | Added `sender_blocklist` table |
| `db/add_sender_blocklist.sql` | Migration script |
| `app/routes/blacklist.py` | Added sender blocklist endpoints |
| `smtp_server/sender_blocklist_checker.py` | New module to check blocked senders |
| `smtp_server/handler.py` | Added sender blocklist check |
| `init_db.py` | Added migration |

## Testing

```bash
# Login to get token
TOKEN=$(curl -s -X POST http://localhost:5003/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "the operator@example.com.au", "password": "not-a-real-password"}' | jq -r '.token')

# Block a sender
curl -X POST http://localhost:5003/api/blacklist/sender \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"email": "spam@spammer.com", "notes": "Spam sender"}'

# Block a domain
curl -X POST http://localhost:5003/api/blacklist/sender \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"domain": "spamdomain.com", "notes": "Spam domain"}'

# Check if blocked
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:5003/api/blacklist/sender/check?email=test@spamdomain.com"

# List blocked senders
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:5003/api/blacklist/sender

# Unblock
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
  http://localhost:5003/api/blacklist/sender/1
```

## Notes

- Blocked emails are rejected at SMTP level (before storage)
- Both specific emails and domains can be blocked
- Blocking a domain blocks ALL emails from that domain
- Check endpoint works for both blocked emails and domains
