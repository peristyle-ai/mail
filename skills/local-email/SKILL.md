---
name: local-email
description: Access a local Python/PostgreSQL mail server API for mailbox login, inbox listing, email read/search, send, move, star, delete, delivery-status checks, and per-domain outbound relay and webhook-secret management. Use when retrieving API keys or messages from the inbox, sending mail via the local server, checking delivery, or debugging email-server auth/API behavior.
version: 1.4.0
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

Use this skill to interact with a Python/PostgreSQL mail server via its HTTP API.

## Requirements

Configure these environment variables (or in `.env`):

| Variable | Description | Example |
|----------|-------------|---------|
| `EMAIL_SERVER` | Base URL of the mail server | `http://localhost:5003` |
| `EMAIL_ADDRESS` | Email account to send from | `evie@yourdomain.com` |
| `EMAIL_PASSWORD` | Account password | `your_password` |
| `EMAIL_TO` | Default recipient (optional) | `user@domain.com` |

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

### login — Test mailbox authentication

```bash
python skills/local-email/scripts/mail_api.py login
```

## API Reference

See `references/api.md` for the full endpoint documentation.

## Notes

- The mail server must be running and reachable at `EMAIL_SERVER`
- Authentication is per-account — each email address is a separate mailbox
- Inbound mail is stored in PostgreSQL; outbound uses either verified per-domain relay config or direct MX delivery
- Inbound webhook (`POST /inbound`) requires no auth — called by SMTP2GO/Cloudflare Email Workers
- Folder IDs can be found via the `folders` command
- Relay config is managed via the `domains`, `domain-set-relay`, and `domain-verify-relay` commands
- Per-domain inbound auth is managed via `domain-set-webhook-secret` and `domain-rotate-webhook-secret`
- Do not print secrets, passwords, bearer tokens, or API keys into chat unless the user explicitly asks
