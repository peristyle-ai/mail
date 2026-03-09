# Mail Server: Backfill HTML for Existing Emails

## Context

The HTML email support was successfully added, but existing emails have `html: null` because they were received before the HTML storage was enabled.

For the Content Curator project to extract Medium article URLs, we need HTML content for the 11 existing Medium digest emails.

## Current State

```
Total Medium digests: 11
With HTML: 0
Without HTML: 11
```

All existing emails return:
```json
{
  "id": 544,
  "body": "Stories for the operator the operator\n...",
  "html": null,
  ...
}
```

## Requirements

### Backfill HTML from Raw Email Storage

If raw email files are stored on disk (e.g., `.eml` files), re-parse them to extract HTML bodies:

1. **Find raw email storage location** - Check where emails are stored on disk
2. **Re-parse with MIME extraction** - Use the `extract_bodies()` function
3. **Update database records** - Set `body_html` for existing emails

### Implementation Approach

```python
import os
from email import message_from_string

def backfill_html_bodies():
    """
    Re-process stored raw emails to extract HTML content.
    """
    # Adjust path based on actual storage location
    raw_email_dir = "/path/to/email/storage"
    
    for email_id in get_existing_email_ids():
        # Get raw email source (from .eml file or however stored)
        raw_path = f"{raw_email_dir}/{email_id}.eml"
        
        if os.path.exists(raw_path):
            with open(raw_path, 'r') as f:
                raw_content = f.read()
            
            # Re-parse to extract HTML
            plain_text, html = extract_bodies(raw_content)
            
            # Update database
            update_email_body_html(email_id, html)
```

### Alternative: Check Database for Raw Source

If raw email source is stored in the database:

```sql
-- Check if there's a raw source column
SELECT column_name FROM information_schema.columns 
WHERE table_name = 'emails';

-- If raw_source or similar exists:
SELECT id, raw_source FROM emails WHERE body_html IS NULL LIMIT 1;
```

If raw source exists in DB, a Python script can iterate and backfill.

## Files That May Need Updates

| File | Change |
|------|--------|
| `scripts/backfill_html.py` (new) | Script to re-parse and update existing emails |
| `smtp_server/email_storage.py` | May need helper to access raw email files |

## Testing After Backfill

```bash
# Should now return HTML for existing emails
curl -H "Authorization: Bearer $TOKEN" http://localhost:5003/api/emails/544 | jq '.html' | head -100
```

## Contact

This document is for the mail server agent. The Content Curator project is at `/opt/py_pg_accounts/git/email_parser`.
