# Mail Server API: HTML Email Body Support - Integration Guide

## Implementation Status: COMPLETE

## ⚠️ Important: Existing Email Limitations

**The 223 existing emails (including 4 Medium digests) CANNOT be backfilled** because:
- Raw email content was not stored when emails were received
- Only plain text body and headers were extracted
- HTML content was discarded during email processing

**Future emails will have HTML content** - raw email storage is now enabled.

## Changes Made

### 1. Database Schema Updated

Added `body_html` and `raw_email` columns to the `emails` table:

```sql
-- Migration: db/add_body_html.sql
ALTER TABLE emails ADD COLUMN IF NOT EXISTS body_html TEXT;
ALTER TABLE emails ADD COLUMN IF NOT EXISTS raw_email TEXT;
```

To apply migration to an existing database:
```bash
psql -d mail_server -f db/add_body_html.sql
```

### 2. Email Storage Updated

The email storage now:
- Extracts both plain text and HTML bodies using `extract_bodies()`
- Stores the full raw MIME content in `raw_email` column
- Future emails can be re-processed if needed

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
| `db/schema.sql` | Added `body_html` and `raw_email` columns |
| `db/add_body_html.sql` | Migration script |
| `smtp_server/email_storage.py` | Now extracts HTML and stores raw email |
| `app/routes/emails.py` | Added `format_email_response()` to map `body_html` to `html` |
| `app/routes/search.py` | Added `format_email_response()` for search results |
| `init_db.py` | Added migration execution |
| `scripts/backfill_html.py` | Script to backfill HTML from raw_email (for future use) |

## Current Email Status

```
Total emails: 223
With raw_email stored: 0
With HTML extracted: 0
Medium/digest emails: 4
```

**To get HTML for Medium digest emails:**
1. Wait for new Medium digest emails (they will have HTML)
2. Or use the Content Curator's email fetching feature to get new emails

## Testing

Run the HTML email tests:
```bash
pytest tests/test_html_emails.py -v
```

Check status:
```bash
python scripts/backfill_html.py --status
```

## Usage Example

```bash
# Login
TOKEN=$(curl -s -X POST http://localhost:5003/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "the operator@example.com.au", "password": "not-a-real-password"}' | jq -r '.token')

# Fetch email with HTML body (new emails only)
curl -H "Authorization: Bearer $TOKEN" http://localhost:5003/api/emails/544 | jq '.html'
```

## For Content Curator Project

When extracting article URLs from **new** Medium digest emails, use the `html` field:

```python
import requests

response = requests.get(
    f"{MAIL_SERVER_API_URL}/api/emails/{email_id}",
    headers={"Authorization": f"Bearer {token}"}
)
email = response.json()

# Article URLs are in the HTML field (for new emails)
html_content = email.get('html', '')

if html_content:
    # Extract article URLs from HTML
    import re
    article_urls = re.findall(r'https://medium\.com/@[a-zA-Z0-9_]+/[a-zA-Z0-9-]+[a-f0-9]{12,}', html_content)
else:
    # Fallback: check plain text or wait for new email
    pass
```

## Notes

- **Existing emails**: `html: null` - cannot be recovered
- **New emails**: `html` will contain HTML content
- The `body` field (plain text) is always available as a fallback
- HTML content is preserved exactly as received from the email sender
