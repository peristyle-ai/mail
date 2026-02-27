# Mail Server API: HTML Email Body Support - Integration Guide

## Implementation Status: COMPLETE

## Changes Made

### 1. Database Schema Updated

Added `body_html` column to the `emails` table:

```sql
-- Migration: db/add_body_html.sql
ALTER TABLE emails ADD COLUMN IF NOT EXISTS body_html TEXT;
```

To apply migration to an existing database:
```bash
psql -d mail_server -f db/add_body_html.sql
```

### 2. Email Parsing Updated

The `extract_bodies()` function in `smtp_server/email_storage.py` now extracts both plain text and HTML from multipart emails.

### 3. API Response Updated

Both `/api/emails` and `/api/emails/{id}` now return the `html` field:

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

## Files Changed

| File | Change |
|------|--------|
| `db/schema.sql` | Added `body_html` column |
| `db/add_body_html.sql` | Migration script |
| `smtp_server/email_storage.py` | Renamed `extract_email_body` to `extract_bodies`, extracts both plain text and HTML |
| `app/routes/emails.py` | Added `format_email_response()` to map `body_html` to `html` |
| `app/routes/search.py` | Added `format_email_response()` for search results |
| `init_db.py` | Added migration execution |

## Testing

Run the HTML email tests:
```bash
pytest tests/test_html_emails.py -v
```

## Usage Example

```bash
# Login
TOKEN=$(curl -s -X POST http://localhost:5003/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "the operator@example.com.au", "password": "not-a-real-password"}' | jq -r '.token')

# Fetch email with HTML body
curl -H "Authorization: Bearer $TOKEN" http://localhost:5003/api/emails/544 | jq '.html'
```

## For Content Curator Project

When extracting article URLs from Medium digest emails, use the `html` field instead of `body`:

```python
import requests

response = requests.get(
    f"{MAIL_SERVER_API_URL}/api/emails/{email_id}",
    headers={"Authorization": f"Bearer {token}"}
)
email = response.json()

# Article URLs are in the HTML field
html_content = email.get('html', '')

# Extract article URLs from HTML
import re
article_urls = re.findall(r'https://medium\.com/@[a-zA-Z0-9_]+/[a-zA-Z0-9-]+[a-f0-9]{12,}', html_content)
```

## Notes

- Existing emails will have `html: null` until they are re-received with HTML content
- The `body` field (plain text) is always available as a fallback
- HTML content is preserved exactly as received from the email sender
