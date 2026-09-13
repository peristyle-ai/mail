---
name: local-email
description: Access a local Python/PostgreSQL mail server API for mailbox login, inbox listing, email read/search, send (with optional CC and attachments), move, star, delete, delivery-status checks, and per-domain outbound relay and webhook-secret management. Use when retrieving API keys or messages from the inbox, sending mail via the local server (single or multi-recipient with CC), checking delivery, or debugging email-server auth/API behavior.
version: 1.6.0
metadata:
  openclaw:
    requires:
      env:
        - EMAIL_SERVER
        - EMAIL_ADDRESS
        - EMAIL_PASSWORD
      bins: []
    primaryEnv: EMAIL_ADDRESS
    emoji: "\U0001F4E7"
    homepage: https://github.com/peristyle-ai/mail
    tags:
      - email
      - imap
      - smtp
      - mailbox
---

# Local Email Skill

Use this skill to interact with a Python/PostgreSQL mail server via its HTTPS API.

## Deployment Modes

The mail server supports two distinct modes of operation. Choose the one that
matches your infrastructure.

### Mode 1: Relay (SMTP2GO outbound + Cloudflare inbound)

Best for: home servers, dynamic IPs, NAT/CGNAT, or anywhere port 25 is blocked.
No public MX records or static IP needed.

```
Inbound:  Internet sender → Cloudflare Email Workers → POST /inbound (HTTPS webhook) → Flask API
Outbound: Flask API → queue → SMTP2GO (SMTP AUTH + STARTTLS) → recipient's mail server
```

**How it works:**
- **Inbound:** Cloudflare receives email on your domains (MX records point to
  Cloudflare). Their Email Workers parse it and POST to your `/inbound` webhook
  over HTTPS. No SMTP server involvement from the internet.
- **Outbound:** Your server queues email and delivers via SMTP2GO's authenticated
  relay using STARTTLS encryption. SMTP2GO handles SPF/DKIM/DMARC alignment and
  IP reputation.
- **SMTP server (port 2525):** Only used for local testing and agent scripts on
  the LAN. Not exposed to the internet.

**Setup:**
1. Point MX records to Cloudflare (they provide Email Workers)
2. Configure Cloudflare Email Workers to POST to `https://your-server:5003/inbound`
3. Set `SMTP2GO_WEBHOOK_SECRET` in `.env` for HMAC signature verification
4. Configure per-domain relay via `domain-set-relay` (SMTP2GO credentials)
5. Set `SMTP2GO_API_KEY` in `.env` for outbound relay

### Mode 2: Static IP (direct SMTP inbound + outbound)

Best for: dedicated servers, VPS, or colocation with a static IP and clean
reverse DNS (PTR record).

```
Inbound:  Internet sender → SMTP (port 25/587, STARTTLS) → your server → Flask API
Outbound: Flask API → queue → direct MX delivery (STARTTLS) → recipient's mail server
```

**How it works:**
- **Inbound:** Your server's SMTP daemon listens on port 25 (or 587 for
  submission). Remote mail servers connect directly. STARTTLS encrypts the
  connection. SPF, greylisting, and rate limiting protect against spam.
- **Outbound:** Your server looks up MX records for the recipient domain and
  delivers directly via SMTP with STARTTLS. DKIM signing proves authenticity.
- **SMTP server (port 2525):** Exposed to the internet (or port-forwarded from
  port 25/587). Requires proper PTR record and SPF/DKIM/DMARC DNS records.

**Setup:**
1. Point MX records to your static IP (`mail.example.com`)
2. Ensure PTR record matches your HELO hostname
3. Set up SPF record: `v=spf1 ip4:YOUR_IP -all`
4. Set up DKIM: generate keys, add DNS TXT record
5. Set up DMARC: `_dmarc.example.com` TXT record
6. Configure firewall: allow inbound port 25 (and 587 if using submission)
7. Set `SMTP_REQUIRE_STARTTLS=true` in `.env` for production
8. Optionally configure SMTP2GO as a fallback relay for domains that reject
   direct delivery (Gmail, Outlook are strict about residential IPs)

### Which mode should I use?

| Factor | Mode 1 (Relay) | Mode 2 (Static IP) |
|--------|---------------|-------------------|
| Static IP required | ❌ No | ✅ Yes |
| Port 25 open required | ❌ No | ✅ Yes |
| PTR record required | ❌ No | ✅ Yes |
| SPF/DKIM/DMARC setup | Minimal (SMTP2GO handles) | Full (you manage) |
| IP reputation management | ❌ SMTP2GO handles | ✅ You manage |
| Deliverability to Gmail/Outlook | ✅ Good (SMTP2GO IPs) | ⚠️ Hard (residential IPs often blocked) |
| Complexity | Low | High |
| Cost | SMTP2GO free tier (1000/mo) | Free (your IP) |

**Recommendation:** Start with Mode 1 (relay). It's simpler, more reliable,
and works from anywhere. Move to Mode 2 (static IP) only if you have a
dedicated server with a clean IP and want full control.

## TLS / Encryption

The mail server supports TLS on both the Flask API and the SMTP server.

### Flask API (HTTPS)

The API uses a self-signed TLS certificate. All agent/client connections
should verify against this cert.

**Certificate locations (auto-discovered in order):**
1. `EMAIL_SERVER_CERT` env var (explicit path)
2. `<repo>/certs/server.crt` (repo-relative)
3. `~/.local/share/py_pg_email/server.crt` (user-level)
4. `/usr/local/share/ca-certificates/py_pg_email.crt` (system-level)

**Quick setup (download from server):**
```bash
curl -k -o /tmp/py_pg_email.crt https://<server>:5003/ca.crt
sudo cp /tmp/py_pg_email.crt /usr/local/share/ca-certificates/py_pg_email.crt
sudo update-ca-certificates
```

**No-sudo setup:**
```bash
mkdir -p ~/.local/share/py_pg_email
curl -k -o ~/.local/share/py_pg_email/server.crt https://<server>:5003/ca.crt
```

**Verify:**
```bash
curl https://<server>:5003/health   # should work without -k
```

### SMTP Server (STARTTLS)

The SMTP server supports STARTTLS (opportunistic by default). This encrypts
the connection between mail servers, preventing eavesdropping on the LAN or
internet path.

**How it works:**
- Client connects on port 2525 (plaintext)
- Server advertises `STARTTLS` in EHLO response
- Client issues `STARTTLS` command
- Connection upgrades to TLS (same cert as Flask API by default)
- All subsequent SMTP commands are encrypted

**Configuration:**

| Setting | Env Var | Default | Description |
|---------|---------|---------|-------------|
| Cert path | `SMTP_TLS_CERT_PATH` | `certs/server.crt` | TLS certificate |
| Key path | `SMTP_TLS_KEY_PATH` | `certs/server.key` | TLS private key |
| Require TLS | `SMTP_REQUIRE_STARTTLS` | `false` | Reject commands before STARTTLS |

**Modes:**

| Mode | Setting | Behavior |
|------|---------|----------|
| Opportunistic (default) | `SMTP_REQUIRE_STARTTLS=false` | STARTTLS offered but optional. Plaintext fallback allowed. |
| Required | `SMTP_REQUIRE_STARTTLS=true` | Server rejects `MAIL FROM` until client issues `STARTTLS`. |
| No TLS | (no cert found) | STARTTLS not advertised. Plaintext only. |

**For production (Mode 2 — static IP):**
```bash
# In .env
SMTP_REQUIRE_STARTTLS=true
```

**Testing STARTTLS:**
```bash
# Check if STARTTLS is advertised
python3 -c "
import smtplib
s = smtplib.SMTP('<server>', 2525, timeout=5)
s.ehlo('test')
print('STARTTLS:', s.has_extn('STARTTLS'))
s.quit()
"

# Test TLS upgrade
python3 -c "
import smtplib, ssl
s = smtplib.SMTP('<server>', 2525, timeout=5)
s.ehlo('test')
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE
s.starttls(context=ctx)
s.ehlo('test')
print('TLS upgrade OK')
s.quit()
"
```

## Requirements

Configure these environment variables (or in `.env`):

| Variable | Description | Example |
|----------|-------------|---------|
| `EMAIL_SERVER` | Base URL of the mail server | `https://192.168.4.41:5003` |
| `EMAIL_ADDRESS` | Email account to send from | `evie@yourdomain.com` |
| `EMAIL_PASSWORD` | Account password | `your_password` |
| `EMAIL_TO` | Default recipient (optional) | `user@domain.com` |
| `EMAIL_SERVER_CERT` | Path to TLS cert (optional) | `/usr/local/share/ca-certificates/py_pg_email.crt` |

## Quick start

```bash
# List inbox
python skills/local-email/scripts/mail_api.py list --limit 20

# List emails in a specific folder
python skills/local-email/scripts/mail_api.py list --folder Inbox

# Search inbox
python skills/local-email/scripts/mail_api.py search --query "subject:order"

# Read a specific email
python skills/local-email/scripts/mail_api.py read --id 880

# Send a plain email
python skills/local-email/scripts/mail_api.py send \
  --to "recipient@example.com" \
  --subject "Hello" \
  --body "Message text"

# Send to multiple recipients
python skills/local-email/scripts/mail_api.py send \
  --to "user1@example.com" \
  --to "user@example.com" \
  --subject "Hello" \
  --body "Message text"

# Send with CC recipients (mixed local + external)
python skills/local-email/scripts/mail_api.py send \
  --to "primary@external.com" \
  --cc "teammate@example.com" \
  --cc "manager@external.com" \
  --subject "Project update" \
  --body "FYI all"

# Move email to a different folder
python skills/local-email/scripts/mail_api.py move --id 880 --folder-id 137

# List folders
python skills/local-email/scripts/mail_api.py folders

# List configured domains
python skills/local-email/scripts/mail_api.py domains

# Configure SMTP2GO relay for a domain
python skills/local-email/scripts/mail_api.py domain-set-relay \
  --domain "example.com" \
  --provider smtp2go \
  --username "example.com" \
  --password "smtp-password" \
  --from-address "support@example.com"

# Verify relay credentials
python skills/local-email/scripts/mail_api.py domain-verify-relay --domain "example.com"

# Set a per-domain inbound webhook secret
python skills/local-email/scripts/mail_api.py domain-set-webhook-secret \
  --domain "example.com" \
  --secret "replace-with-a-long-random-secret"

# Rotate a per-domain inbound webhook secret
python skills/local-email/scripts/mail_api.py domain-rotate-webhook-secret --domain "example.com"

# Delete an email
python skills/local-email/scripts/mail_api.py delete --id 880

# Mark as read
python skills/local-email/scripts/mail_api.py mark-read --id 880

# Toggle star
python skills/local-email/scripts/mail_api.py star --id 880

# Check delivery status
python skills/local-email/scripts/mail_api.py status --id 1251

# Test authentication
python skills/local-email/scripts/mail_api.py login
```

## Commands

### list — List mailbox contents

```bash
python skills/local-email/scripts/mail_api.py list --limit 20
python skills/local-email/scripts/mail_api.py list --folder Inbox
python skills/local-email/scripts/mail_api.py list --folder Sent
```

### search — Search mailbox

```bash
python skills/local-email/scripts/mail_api.py search --query "coinglass api key"
```

### read — Read a specific email

```bash
python skills/local-email/scripts/mail_api.py read --id 880
```

### send — Send an email

```bash
python skills/local-email/scripts/mail_api.py send \
  --to "recipient@example.com" \
  --subject "Subject line" \
  --body "Email body text"

python skills/local-email/scripts/mail_api.py send \
  --to "user1@example.com" \
  --to "user@example.com" \
  --subject "Subject line" \
  --body "Email body text"
```

#### Send with CC recipients

The `--cc` flag mirrors RFC 5322 CC semantics: addresses are stamped into the
`Cc:` header, receive their own local Inbox copy (when local), and each
external CC is queued for delivery. The sender sees them in their own Sent
view via `email_recipients` with `recipient_type='cc'`. Repeat `--cc` for
multiple addresses or pass a comma-separated list.

```bash
python skills/local-email/scripts/mail_api.py send \
  --to "primary@external.com" \
  --cc "teammate@example.com" \
  --cc "manager@external.com" \
  --subject "Project update" \
  --body "FYI all"
```

A recipient that appears in both `--to` and `--cc` is kept as `to` (the more
prominent role).

#### Send with attachments (PDF, image, etc.)

When `--attachment` is provided the email is sent as a multipart MIME message
via the `/api/emails/mime` endpoint. Repeat `--attachment` for multiple files.

```bash
python skills/local-email/scripts/mail_api.py send \
  --to "customer@example.com" \
  --from-addr "payroll@example.com" \
  --subject "Invoice INV-12345" \
  --body "Please find the invoice attached." \
  --attachment "./invoice.pdf"
```

When using attachments, `--from-addr` is required so the server stamps the
correct sender (defaults to `EMAIL_ADDRESS` otherwise).

You can combine `--cc` with `--attachment`; the same CC semantics apply.

#### Send a prebuilt MIME message from a file

For full control over the MIME structure (e.g. when you've already built a
`message/rfc822` blob with `email.mime.*`), use `send-mime`:

```bash
python skills/local-email/scripts/mail_api.py send-mime \
  --to "customer@example.com" \
  --from-addr "payroll@example.com" \
  --subject "Invoice INV-12345" \
  --mime-file "./message.eml"
```

**Encoding note (important):** the `/api/emails/mime` endpoint expects the
`mime_content` field to contain a **complete RFC 822 message** as a JSON
string. Encode raw bytes via `.decode("latin-1")` (not base64) — the server
parses the message directly. The CLI handles this automatically; only relevant
if you're calling the API from your own code.

### send-mime — Send a prebuilt RFC 822 MIME message

For full control over the MIME structure (e.g. you built a `message/rfc822`
blob with `email.mime.*` in your own code), use `send-mime`:

```bash
python skills/local-email/scripts/mail_api.py send-mime \
  --to "recipient@example.com" \
  --from-addr "payroll@example.com" \
  --subject "Invoice INV-12345" \
  --mime-file "./message.eml"
```

The `--subject` and `--from-addr` are used for envelope/sender metadata; they
are NOT added to the MIME body — that comes from the file.

### move — Move an email to a different folder

```bash
python skills/local-email/scripts/mail_api.py move --id 880 --folder-id 137
```

### folders — List all folders

```bash
python skills/local-email/scripts/mail_api.py folders
```

### domains — List configured domains

```bash
python skills/local-email/scripts/mail_api.py domains
```

### domain-get — Get one domain configuration

```bash
python skills/local-email/scripts/mail_api.py domain-get --domain "example.com"
```

### domain-set-relay — Set relay config for a domain

```bash
python skills/local-email/scripts/mail_api.py domain-set-relay \
  --domain "example.com" \
  --provider smtp2go \
  --username "example.com" \
  --password "smtp-password" \
  --from-address "support@example.com"
```

### domain-verify-relay — Verify relay credentials

```bash
python skills/local-email/scripts/mail_api.py domain-verify-relay --domain "example.com"
```

### domain-delete-relay — Remove relay config

```bash
python skills/local-email/scripts/mail_api.py domain-delete-relay --domain "example.com"
```

### domain-set-webhook-secret — Set a per-domain inbound webhook secret

```bash
python skills/local-email/scripts/mail_api.py domain-set-webhook-secret \
  --domain "example.com" \
  --secret "replace-with-a-long-random-secret"
```

### domain-rotate-webhook-secret — Rotate and return a new inbound webhook secret

```bash
python skills/local-email/scripts/mail_api.py domain-rotate-webhook-secret --domain "example.com"
```

### delete — Delete an email

```bash
python skills/local-email/scripts/mail_api.py delete --id 880
```

### mark-read — Mark email as read

```bash
python skills/local-email/scripts/mail_api.py mark-read --id 880
```

### star — Toggle starred status

```bash
python skills/local-email/scripts/mail_api.py star --id 880
```

### status — Check delivery status of a sent email

```bash
python skills/local-email/scripts/mail_api.py status --id 1251
```

This checks the mail server's own delivery state only, for example whether the
message was queued, retried, or successfully handed off to a direct MX server
or SMTP relay.

#### Verifying final downstream delivery with SMTP2GO

If the domain uses SMTP2GO relay and you have an `SMTP2GO_API_KEY`, you can
verify whether SMTP2GO reports the message as actually delivered to the
recipient's provider after handoff.

Use SMTP2GO's `POST /v3/activity/search` endpoint with filters such as:

- `search_recipient`
- `search_subject`
- `start_date`
- `end_date`
- optionally `only_latest_by_sent=true`

Required SMTP2GO API key permissions:

- **Activity**
- **Statistics** is useful for related reporting, but the delivery lookup itself uses **Activity**
- **Webhooks** is not required for manual activity lookup, but is useful if you want ongoing delivery-event ingestion

Example direct API call:

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

Look for an event like:

- `event: delivered`
- `smtp_response: 250 ...`

That confirms SMTP2GO delivered the email onward to the recipient's mail
provider. If your API key lacks the needed permission, SMTP2GO returns an
`ENDPOINT_PERMISSION_DENIED` error.

### login — Test mailbox authentication

```bash
python skills/local-email/scripts/mail_api.py login
```

## API Reference

See `references/api.md` for the full endpoint documentation.

## Notes

- The mail server must be running and reachable at `EMAIL_SERVER`
- Authentication is per-account — each email address is a separate mailbox
- **Deployment modes:** See "Deployment Modes" above for the two supported configurations (relay vs static IP)
- Inbound mail is stored in PostgreSQL; outbound uses either verified per-domain relay config (Mode 1) or direct MX delivery (Mode 2)
- Inbound webhook (`POST /inbound`) requires no auth — called by Cloudflare Email Workers (Mode 1) or SMTP2GO
- SMTP server (port 2525) supports STARTTLS — see "TLS / Encryption" above
- Folder IDs can be found via the `folders` command
- Relay config is managed via the `domains`, `domain-set-relay`, and `domain-verify-relay` commands
- Per-domain inbound auth is managed via `domain-set-webhook-secret` and `domain-rotate-webhook-secret`
- Final SMTP2GO delivery confirmation is external to `py_pg_email` and requires querying SMTP2GO Activity Search with an appropriately scoped API key
- Do not print secrets, passwords, bearer tokens, or API keys into chat unless the user explicitly asks
