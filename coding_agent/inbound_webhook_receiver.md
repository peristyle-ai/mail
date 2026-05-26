# Inbound SMTP2GO Webhook Receiver — Implementation Plan

## Why This Is Needed

### Current State

The `one_shot_email` infrastructure was set up to receive inbound emails via SMTP2GO's webhook forwarding:

```
SMTP2GO → receives email for example.com.au → HTTP POST to https://mail.example.com.au/inbound
```

However, **the `/inbound` endpoint does not exist in py_pg_email**:

```
$ curl -I https://mail.example.com.au/inbound
HTTP/2 404  ← nothing listening
```

The Cloudflare Tunnel is running correctly (`mail.example.com.au` → `192.168.4.41:5003`), but py_pg_email has no route to handle the webhook payload.

### Consequences of Not Implementing

1. **All inbound emails sent to `*@example.com.au` are lost** — SMTP2GO receives them but gets 404 from our server
2. **The `mail.example.com.au` tunnel is wasted** — traffic arrives but nothing processes it
3. **Users cannot receive email at their custom domains** — only send works

### Why This Matters

The SMTP2GO relay (outbound) is working. For a complete email solution, **inbound** is equally important:
- Customer registers `example.com` via agieth
- Sets MX to SMTP2GO
- Sends email to `contact@example.com`
- SMTP2GO forwards to `https://mail.example.com/inbound` → py_pg_email stores it → user reads via API

Without this, custom-domain email is send-only.

---

## What SMTP2GO Sends to the Webhook

When SMTP2GO receives an email for a configured domain, it POSTs to the webhook URL with:

**Content-Type:** `multipart/form-data` or `application/json`

**Form fields (typical SMTP2GO format):**
- `from` — sender email address
- `to` — recipient email address
- `subject` — email subject
- `text` — plain text body (if present)
- `html` — HTML body (if present)
- `sender_ip` — sender's IP address
- `attachments[]` — attachment files (multipart)

Or as JSON:
```json
{
  "from": "sender@example.com",
  "to": "recipient@example.com.au",
  "subject": "Hello",
  "text": "Message body",
  "html": "<html><body>HTML body</body></html>",
  "sender_ip": "203.0.113.50"
}
```

SMTP2GO may also send as `multipart/form-data` with the email MIME content in a field called `mail`.

---

## What to Implement

### New Route: `POST /inbound`

**File:** `app/routes/inbound.py` (new file)

This endpoint must:
1. Accept POST requests from SMTP2GO (no JWT auth required — SMTP2GO is the caller)
2. Parse sender, recipient, subject, body from the payload
3. Determine which local user owns the recipient domain
4. Store the email in the database (same `emails` table as SMTP received emails)
5. Return HTTP 200 to SMTP2GO so it doesn't retry

**Security considerations:**
- **No JWT auth** — this endpoint is called by SMTP2GO's servers, not by end users
- **IP allowlist** — only accept webhook POSTs from SMTP2GO's IP ranges (SMTP2GO publishes their webhook IPs)
- **Rate limiting** — accept one request per email, but validate structure
- **No user input executed** — treat all fields as untrusted strings

### SMTP2GO Signature Verification (if available)

SMTP2GO may sign webhook requests with an `X-SMTP2GO-Signature` header using HMAC-SHA256. If available, verify it to prevent spoofing.

---

## Implementation Details

### Step 1 — Create the Route File

**File:** `app/routes/inbound.py`

```python
from flask import Blueprint, request, jsonify
from email.utils import parseaddr
import re

inbound_bp = Blueprint('inbound', __name__)

@inbound_bp.route('/inbound', methods=['POST'])
def receive_inbound_webhook():
    """
    Receive inbound email webhook from SMTP2GO.

    SMTP2GO POSTs to this endpoint when an email is received for
    a domain configured in SMTP2GO's inbound routing.

    Content-Type may be:
    - application/x-www-form-urlencoded (SMTP2GO default)
    - multipart/form-data (when attachments present)
    - application/json (rare)

    Fields:
        from:     sender email address
        to:       recipient email address
        subject:  email subject
        text:     plain text body (optional)
        html:     HTML body (optional)
        sender_ip: sender's IP address (optional)
    """
    # ── 1. Parse the payload ────────────────────────────────────────────────
    content_type = request.content_type or ""

    if "application/x-www-form-urlencoded" in content_type or \
       "multipart/form-data" in content_type:
        sender    = request.form.get("from", "")
        recipient = request.form.get("to", "")
        subject   = request.form.get("subject", "")
        text_body = request.form.get("text", "")
        html_body = request.form.get("html", "")
        sender_ip = request.form.get("sender_ip", "")
    elif "application/json" in content_type:
        data      = request.get_json(silent=True) or {}
        sender    = data.get("from", "")
        recipient = data.get("to", "")
        subject   = data.get("subject", "")
        text_body = data.get("text", data.get("body", ""))
        html_body = data.get("html", "")
        sender_ip = data.get("sender_ip", "")
    else:
        return jsonify({"error": "Unsupported content type"}), 400

    # ── 2. Basic validation ─────────────────────────────────────────────────
    if not sender or not recipient:
        return jsonify({"error": "Missing sender or recipient"}), 400

    # ── 3. Resolve recipient to local user ───────────────────────────────────
    # Extract email address from "To: recipient@domain.com" or just "recipient@domain.com"
    recipient_email = extract_email(recipient)

    user_id = resolve_recipient_user(recipient_email)
    if not user_id:
        # Recipient not a local user — either forward or discard
        return jsonify({"status": "rejected", "reason": "unknown recipient"}), 200

    # ── 4. Optional: check sender blocklist ─────────────────────────────────
    sender_email = extract_email(sender)
    if is_sender_blocked(sender_email):
        return jsonify({"status": "blocked"}), 200

    # ── 5. Store the email ─────────────────────────────────────────────────
    email_id = store_inbound_email(
        user_id=user_id,
        sender=sender_email,
        recipient=recipient_email,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        sender_ip=sender_ip,
    )

    return jsonify({"status": "received", "email_id": email_id}), 200
```

### Step 2 — Helper Functions

**Add to `app/routes/inbound.py` (or `app/utils/inbound.py`):**

```python
def extract_email(address: str) -> str:
    """Extract email address from 'Name <email@domain.com>' or plain email."""
    parsed = parseaddr(address)
    if parsed[1]:
        return parsed[1].lower().strip()
    return address.lower().strip()


def resolve_recipient_user(recipient_email: str) -> int | None:
    """Look up local user by email address. Returns user_id or None."""
    from app.db import get_db
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM users WHERE email = %s AND is_local = TRUE",
        (recipient_email,)
    )
    row = cursor.fetchone()
    cursor.close()
    return row["id"] if row else None


def is_sender_blocked(sender_email: str) -> bool:
    """Check if sender or sender domain is in the blocklist."""
    from app.db import get_db
    domain = sender_email.split("@")[-1] if "@" in sender_email else ""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id FROM sender_blocklist
        WHERE email = %s OR (domain = %s AND email IS NULL)
        LIMIT 1
    """, (sender_email, domain))
    row = cursor.fetchone()
    cursor.close()
    return row is not None


def store_inbound_email(user_id, sender, recipient, subject,
                        text_body, html_body, sender_ip) -> int:
    """Insert inbound email into database. Returns email_id."""
    from app.db import get_db
    from datetime import datetime

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO emails
          (sender_id, recipient_id, subject, body, body_html,
           sender_ip, is_read, is_starred, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, FALSE, FALSE, %s)
        RETURNING id
    """, (user_id, user_id, subject, text_body, html_body,
          sender_ip, datetime.utcnow()))

    email_id = cursor.fetchone()[0]
    conn.commit()
    cursor.close()
    return email_id
```

### Step 3 — Register the Blueprint

**File:** `app/__init__.py` or `app/routes/__init__.py`

```python
from app.routes.inbound import inbound_bp

def create_app():
    app = Flask(__name__)
    # ... existing setup ...
    app.register_blueprint(inbound_bp)
    return app
```

### Step 4 — Update `coding_agent/AGENTS.md`

Add `inbound_webhook_receiver.md` to the index of known plans so future agents can find it.

---

## Testing Plan

### Test 1 — Direct curl to the webhook
```bash
curl -X POST https://mail.example.com.au/inbound \
  -F "from=user@example.com" \
  -F "to=the operator@example.com.au" \
  -F "subject=Test Inbound" \
  -F "text=This is a test email"

# Expected: {"status": "received", "email_id": <n>}
```

### Test 2 — Verify email stored
```bash
# Login
TOKEN=$(curl -s -X POST http://192.168.4.41:5003/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"the operator@example.com.au","password":"password123"}' \
  | python -c "import sys,json; print(json.load(sys.stdin)['token'])")

# List emails — should show new email
curl -H "Authorization: Bearer $TOKEN" \
  "http://192.168.4.41:5003/api/emails?folder=Inbox" \
  | python -m json.tool | grep -A5 '"subject": "Test Inbound"'
```

### Test 3 — Unknown recipient returns 200 (not 404)
```bash
curl -X POST https://mail.example.com.au/inbound \
  -F "from= attacker@spam.com" \
  -F "to= nobody@example.com.au" \
  -F "subject= Spam"

# Expected: {"status": "rejected"} — returns 200 so SMTP2GO doesn't retry
```

---

## Files to Create/Modify

| File | Action |
|------|--------|
| `app/routes/inbound.py` | **Create** — new blueprint with `/inbound` route |
| `app/__init__.py` | **Modify** — register `inbound_bp` blueprint |
| `coding_agent/inbound_webhook_receiver.md` | **Create** — this document |

---

## Out of Scope (for future)

- Forwarding to external email if recipient is not local
- DMARC/SPF validation of sender

## Completed (previously out of scope)

- ~~Attachment handling in the webhook~~ — Now implemented: MIME content parsed from `mail`/`raw_email`, attachments extracted and saved to disk
- ~~Storing raw MIME content for replay~~ — Now implemented: `raw_email` column stores decoded MIME content

## Implementation Status (2026-05-23)

The `/inbound` endpoint is fully implemented with the following features beyond the original plan:

- **Cloudflare Email Workers support**: `raw_email` field name, `from_address`/`sender` fallback for `from`, `rcpt`/`recipient` for `to`, `subjects` for `subject`, `srchost` for `sender_ip`
- **Base64 auto-decoding**: Cloudflare Workers send Base64-encoded MIME; auto-detected and decoded
- **MIME body extraction**: When `text`/`html` fields are empty, raw MIME is parsed to extract text/plain and text/html parts
- **File upload support**: MIME content accepted as file upload in multipart/form-data
- **Attachment extraction**: Attachments and inline images extracted from MIME and saved to disk
- **Form size limits**: Werkzeug `max_form_memory_size` set to 50MB (overrides default 500KB)
- **53 tests** covering all features including Base64 decoding, field fallbacks, MIME extraction, and payload limits
- Storing raw MIME content for replay

