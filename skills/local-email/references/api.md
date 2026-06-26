# Local Email API Reference

## Overview

This is the HTTP API for the Python/PostgreSQL mail server. It provides SMTP sending/receiving via a REST API, folder management, attachments, blacklist management, per-domain outbound relay configuration, and inbound webhook processing.

## Server

- **Base URL:** Set via `EMAIL_SERVER` env var (e.g. `http://localhost:5003`)
- **Swagger UI:** `/docs`
- **API spec:** `/api/spec.json`
- **Health check:** `GET /health`

## Authentication

### Login

```
POST /auth/login
Content-Type: application/json

{"email": "user@example.com", "password": "your_password"}
```

**Response:**
```json
{"token": "..."}
```

Use the returned token as `Authorization: Bearer <token>` header for subsequent requests.

### Register

```
POST /auth/register
Content-Type: application/json

{"email": "newuser@example.com", "password": "your_password", "name": "New User"}
```

## Endpoints

### Email Operations

| Method | Path | Description |
|--------|-------|-------------|
| `GET` | `/api/emails` | List emails (optional `?folder=Inbox`, `?sent=true`) |
| `GET` | `/api/emails/{id}` | Read one email by ID |
| `POST` | `/api/emails` | Send a plain text email to one or more recipients (supports `to` and `cc`) |
| `POST` | `/api/emails/mime` | Send a MIME email (multipart/attachments); supports `to` and `cc` |
| `DELETE` | `/api/emails/{id}` | Delete an email |
| `POST` | `/api/emails/{id}/read` | Mark email as read |
| `POST` | `/api/emails/{id}/star` | Toggle starred status |
| `POST` | `/api/emails/{id}/move` | Move email to a different folder |
| `GET` | `/api/emails/{id}/delivery-status` | Check outbound delivery status |

`GET /api/emails/{id}/delivery-status` only reports what this mail server knows:

- queued
- retrying
- failed before handoff
- successfully handed off to direct MX or a configured relay

It does **not** by itself prove downstream final delivery after a third-party
relay (such as SMTP2GO) accepts the message.

### Folder Operations

| Method | Path | Description |
|--------|-------|-------------|
| `GET` | `/api/folders` | List all folders for current user |
| `POST` | `/api/folders` | Create a new folder |

### Search

| Method | Path | Description |
|--------|-------|-------------|
| `GET` | `/api/search?q=...` | Search mailbox by query |

### Attachments

| Method | Path | Description |
|--------|-------|-------------|
| `POST` | `/api/emails/{id}/attachments` | Upload an attachment |
| `GET` | `/api/emails/{id}/attachments` | List attachments for an email |
| `GET` | `/api/attachments/{id}` | Download an attachment |
| `DELETE` | `/api/attachments/{id}` | Delete an attachment |

### Blacklist

| Method | Path | Description |
|--------|-------|-------------|
| `GET` | `/api/blacklist/ip` | List IP blacklist entries |
| `POST` | `/api/blacklist/ip` | Add IP to blacklist |
| `DELETE` | `/api/blacklist/ip/{id}` | Remove IP blacklist entry |
| `DELETE` | `/api/blacklist/ip/address/{ip}` | Remove IP by address |
| `GET` | `/api/blacklist/ip/check/{ip}` | Check if IP is blacklisted |
| `GET` | `/api/blacklist/stats` | Blacklist statistics |
| `GET` | `/api/blacklist/sender` | List sender blocklist entries |
| `POST` | `/api/blacklist/sender` | Add sender to blocklist |
| `DELETE` | `/api/blacklist/sender/{id}` | Remove sender blocklist entry |
| `GET` | `/api/blacklist/sender/check` | Check if sender is blocked |

### Domains / Outbound Relay

| Method | Path | Description |
|--------|-------|-------------|
| `GET` | `/api/domains` | List all domains and relay config |
| `GET` | `/api/domains/{domain}` | Get one domain's relay config |
| `PUT` | `/api/domains/{domain}/relay` | Set or update relay credentials |
| `POST` | `/api/domains/{domain}/relay/verify` | Verify relay credentials by TLS/login |
| `DELETE` | `/api/domains/{domain}/relay` | Remove relay credentials |
| `PUT` | `/api/domains/{domain}/webhook-secret` | Set a per-domain inbound webhook secret |
| `POST` | `/api/domains/{domain}/webhook-secret/rotate` | Rotate and return a new webhook secret |

### Inbound Webhook (no auth required)

| Method | Path | Description |
|--------|-------|-------------|
| `POST` | `/inbound` | Receive inbound email from SMTP2GO/Cloudflare |

**Inbound webhook fields:** `from` (or `from_address`/`sender`), `to` (or `rcpt`/`recipient`), `subject` (or `subjects`), `text` (or `body`), `html`, `sender_ip` (or `srchost`), `mail` (or `raw_email` for Base64-encoded MIME). Supports `application/x-www-form-urlencoded`, `multipart/form-data`, and `application/json`.

**Inbound webhook auth:** Use either `X-Webhook-Secret: <plaintext-secret>` for per-domain verification or the legacy `X-SMTP2GO-Signature` HMAC header when a global `SMTP2GO_WEBHOOK_SECRET` is configured.

## Move Email Example

```bash
curl -X POST http://localhost:5003/api/emails/123/move \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"folder_id": 137}'
```

## Multiple Recipient Send Example

```bash
curl -X POST http://localhost:5003/api/emails \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "to": ["user1@example.com", "user@example.com"],
    "subject": "Group Email",
    "body": "Hello everyone"
  }'
```

## CC Send Example

Both `/api/emails` and `/api/emails/mime` accept an optional `cc` field with
the same shape as `to` (a single address string or an array). CC addresses
are stamped into the `Cc:` header, each local CC user gets an Inbox copy, and
each external CC is queued for delivery. If the same address appears in both
`to` and `cc`, it's kept as `to`.

```bash
curl -X POST http://localhost:5003/api/emails \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "to": "primary@external.com",
    "cc": ["teammate@example.com", "manager@external.com"],
    "subject": "Project update",
    "body": "FYI all"
  }'
```

Successful response includes the `cc_count` of CC recipients:

```json
{
  "id": 7810,
  "queued": true,
  "cc_count": 2
}
```

## MIME Send (attachments) Example

Use `/api/emails/mime` to send a multipart message (HTML body, PDF/image
attachments, custom headers, etc.). The `mime_content` field must contain a
**complete RFC 822 message** as a JSON string — not base64, not a bare body.

To round-trip raw bytes 1:1 through JSON (which is UTF-8), use latin-1:
`mime_bytes.decode("latin-1")`. Every byte 0x00-0xFF maps to a valid Unicode
code point, so JSON will serialize and parse the bytes losslessly. The server
parses the decoded string as a real RFC 822 message.

Minimal Python example (body + one PDF attachment):

```python
import base64
import json
import urllib.request
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

msg = MIMEMultipart()
msg["From"] = "payroll@example.com"
msg["To"] = "customer@example.com"
msg["Subject"] = "Invoice INV-12345"
msg.attach(MIMEText("Please find the invoice attached.", "plain", "utf-8"))

with open("./invoice.pdf", "rb") as f:
    pdf_bytes = f.read()
att = MIMEApplication(pdf_bytes, _subtype="pdf", Name="invoice.pdf")
att.add_header("Content-Disposition", "attachment", filename="invoice.pdf")
msg.attach(att)

raw_mime = msg.as_bytes().decode("latin-1")  # NOT base64
payload = json.dumps({
    "to": ["customer@example.com"],
    "from": "payroll@example.com",
    "subject": "Invoice INV-12345",
    "mime_content": raw_mime,
}).encode("utf-8")

req = urllib.request.Request(
    "http://localhost:5003/api/emails/mime",
    data=payload,
    headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer <token>",
    },
    method="POST",
)
with urllib.request.urlopen(req) as resp:
    print(resp.read().decode())
```

#### CC recipients with `/api/emails/mime`

`/api/emails/mime` accepts an optional `cc` field with the same shape as `to`
(string or array). When present, the request-level `cc` is used. When
omitted, the server falls back to any `Cc:` header in the parsed MIME
message itself. The request-level value always wins. Display names are
parsed (`Friend <addr>` → `addr`).

Common failure modes:

- **400 "mime_content is required"** — you forgot the field, or it's `null`.
- **400 "Failed to parse MIME message"** — the server could not parse the
  string as RFC 822. Most often caused by base64-encoding the bytes (the
  server does not base64-decode) or by sending a bare body without headers.
- **201 with no delivery** — check that the `From` header in the MIME body
  matches a real local mailbox (or matches the JWT user); the server may
  accept the message but fail to assign a sender.
- **CC recipients silently missing from the queue** — pass `cc` explicitly
  in the request body, or include a `Cc:` header in the MIME. The server
  cannot infer CC from anything else.

## Folder Operations Example

```bash
# List folders
curl http://localhost:5003/api/folders \
  -H "Authorization: Bearer <token>"

# Create a folder
curl -X POST http://localhost:5003/api/folders \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "Processed"}'
```

## Domain Relay Examples

```bash
# List domains
curl http://localhost:5003/api/domains \
  -H "Authorization: Bearer <token>"

# Set SMTP2GO relay for a domain
curl -X PUT http://localhost:5003/api/domains/example.com/relay \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "relay_provider": "smtp2go",
    "relay_host": "mail-au.smtp2go.com",
    "relay_port": 2525,
    "relay_username": "example.com",
    "relay_password": "smtp-password",
    "relay_from_address": "support@example.com"
  }'

# Verify relay credentials
curl -X POST http://localhost:5003/api/domains/example.com/relay/verify \
  -H "Authorization: Bearer <token>"

# Set a per-domain inbound webhook secret
curl -X PUT http://localhost:5003/api/domains/example.com/webhook-secret \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"webhook_secret": "replace-with-a-long-random-secret"}'

# Rotate a per-domain inbound webhook secret
curl -X POST http://localhost:5003/api/domains/example.com/webhook-secret/rotate \
  -H "Authorization: Bearer <token>"
```

## Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `EMAIL_SERVER` | Mail server base URL | `http://localhost:5003` |
| `EMAIL_ADDRESS` | Sender/recipient email | `evie@example.com` |
| `EMAIL_PASSWORD` | Account password | `your_password` |
| `EMAIL_TO` | Default recipient for send | `user@example.com` |

## Operational Notes

- Search by subject first for fast retrieval of API keys or reports
- Avoid dumping full HTML email bodies unless needed
- When sending mail for tests, prefer small plain-text messages
- The server stores inbound mail in PostgreSQL; outbound uses either verified per-domain relay config or direct MX delivery
- Inbound webhook (`POST /inbound`) requires no auth — called by SMTP2GO/Cloudflare Email Workers
- Base64-encoded MIME content in `raw_email`/`mail` fields is auto-decoded
- When `text`/`html` are empty, body content is extracted from raw MIME
- Relay config is selected by sender domain and only used after `POST /api/domains/{domain}/relay/verify` succeeds
- Per-domain webhook secrets are stored hashed at rest in `domains.webhook_secret`
- `POST /api/domains/{domain}/webhook-secret/rotate` returns the new plaintext secret once; save it immediately

## SMTP2GO Downstream Delivery Verification

If you use SMTP2GO as the outbound relay, final recipient-provider delivery can
be checked via SMTP2GO's Activity Search API after `py_pg_email` has already
reported a successful relay handoff.

SMTP2GO endpoint:

- `POST https://api.smtp2go.com/v3/activity/search`

Recommended search fields:

- `start_date`
- `end_date`
- `search_recipient`
- `search_subject`
- `only_latest_by_sent`

Required SMTP2GO API key permissions:

- **Activity** (required)
- **Statistics** (optional but useful for reporting)
- **Webhooks** (optional; only needed for webhook-based event ingestion)

Example:

```bash
curl -X POST https://api.smtp2go.com/v3/activity/search \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -H "X-Smtp2go-Api-Key: $SMTP2GO_API_KEY" \
  -d '{
    "start_date": "2026-06-17T00:00:00Z",
    "end_date": "2026-06-18T00:00:00Z",
    "search_recipient": "recipient@example.net",
    "search_subject": "Invoice INV-12345",
    "only_latest_by_sent": true,
    "limit": 20
  }'
```

Successful downstream delivery is typically indicated by:

- `event: delivered`
- an SMTP response such as `250 2.0.0 OK ...`

If the key cannot access the endpoint, SMTP2GO returns an API permission error
such as `E_ApiResponseCodes.ENDPOINT_PERMISSION_DENIED`.
