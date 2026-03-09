# Mail Server API: Add HTML Email Body Support

## Context

The Content Curator project extracts article URLs from Medium daily digest emails. Currently, the mail server API only provides plain text email bodies via the `body` field. However, Medium digest emails contain article URLs only in the HTML version, not in plain text.

## Current State

### API Response for `/api/emails`

```json
{
  "id": 544,
  "body": "Stories for the operator the operator\n@the operator_43655 (https://medium.com/@the operator_43655?...)\n...",
  "created_at": "Thu, 26 Feb 2026 21:20:14 GMT",
  "folder_id": 47,
  "headers": "DKIM-Signature: v=1; ...",
  "is_read": false,
  "is_starred": false,
  "sender_id": 268,
  "subject": "How to Spot a Liar in 3 Questions..."
}
```

**Problem**: The `body` field contains only plain text. Article URLs are missing because Medium formats article links like this:

**HTML version** (what we need):
```html
<a href="https://medium.com/@iamjoshmason/how-to-spot-a-liar-3e5b8f04cb8d?...">
  How to Spot a Liar in 3 Questions (Without Them Knowing)
</a>
```

**Plain text version** (what we currently get):
```
Joshua Mason (https://medium.com/@iamjoshmason?source=...)
inE³ - Entertain Enlighten Empower (https://medium.com/the-springboard?source=...)

How to Spot a Liar in 3 Questions (Without Them Knowing)
The secret to detecting deception isn't about body…

5 min read
```

The article URL `@iamjoshmason/how-to-spot-a-liar-3e5b8f04cb8d` is **not present** in plain text - only the author profile URL.

## Requirements

### 1. Add HTML Body to API Response

Modify the email retrieval endpoints to include the HTML body:

**Endpoint**: `GET /api/emails` and `GET /api/emails/{id}`

**Add field**: `html` (or `body_html`)

```json
{
  "id": 544,
  "body": "Stories for the operator the operator\n...",
  "html": "<!DOCTYPE html><html>...</html>",
  "created_at": "Thu, 26 Feb 2026 21:20:14 GMT",
  "folder_id": 47,
  "headers": "...",
  "is_read": false,
  "is_starred": false,
  "sender_id": 268,
  "subject": "How to Spot a Liar in 3 Questions..."
}
```

### 2. Database Changes (if needed)

If emails are stored in the database, ensure the HTML body is stored and retrieved:

```sql
-- If table structure needs updating
ALTER TABLE emails ADD COLUMN IF NOT EXISTS body_html TEXT;
```

### 3. Email Parsing Changes

When receiving/storing emails, extract both text and HTML parts from the MIME message:

```python
# Example structure of a multipart/alternative email:
# --boundary
# Content-Type: text/plain; charset=utf-8
# 
# [plain text body]
# --boundary
# Content-Type: text/html; charset=utf-8
# 
# [HTML body]
# --boundary--
```

Parse using Python's `email` module:

```python
from email import message_from_string

def extract_bodies(raw_email: str) -> tuple[str, str]:
    """
    Extract plain text and HTML bodies from raw email.
    Returns: (plain_text, html)
    """
    msg = message_from_string(raw_email)
    plain_text = ""
    html = ""
    
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            
            # Skip attachments
            if part.get('Content-Disposition') == 'attachment':
                continue
            
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            
            decoded = payload.decode('utf-8', errors='replace')
            
            if content_type == 'text/plain' and not plain_text:
                plain_text = decoded
            elif content_type == 'text/html' and not html:
                html = decoded
    else:
        # Single part email
        payload = msg.get_payload(decode=True)
        decoded = payload.decode('utf-8', errors='replace')
        
        if msg.get_content_type() == 'text/html':
            html = decoded
        else:
            plain_text = decoded
    
    return plain_text, html
```

## Implementation Checklist

- [ ] Modify database schema to store HTML body (if not already stored)
- [ ] Update email parsing to extract HTML from multipart messages
- [ ] Add `html` field to API response for `/api/emails`
- [ ] Add `html` field to API response for `/api/emails/{id}`
- [ ] Backfill existing emails with HTML if available in raw storage
- [ ] Test with Medium digest emails to verify article URLs are present in HTML

## Testing

After implementation, verify by fetching a Medium digest email:

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:5003/api/emails/544 | jq '.html' | head -100
```

Look for article URLs like `https://medium.com/@username/article-slug-abc123`.

## Current Mail Server Config

From Content Curator `.env`:

```
MAIL_SERVER_API_URL=http://192.168.4.41:5003
MAIL_SERVER_EMAIL=the operator@example.com.au
MAIL_SERVER_PASSWORD=not-a-real-password
```

Authentication: POST `/auth/login` with `{"email": "...", "password": "..."}` returns JWT token.

## Contact

This document is for the mail server agent. The Content Curator project is at `/opt/py_pg_accounts/git/email_parser`.
