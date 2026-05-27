# Local Email API Reference

## Overview

This is the HTTP API for the Python/PostgreSQL mail server. It provides SMTP sending/receiving via a REST API, folder management, attachments, blacklist management, and inbound webhook processing.

## Server

- **Base URL:** Set via `EMAIL_SERVER` env var (e.g. `http://192.168.4.41:5003`)
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
| `POST` | `/api/emails` | Send a plain text email |
| `POST` | `/api/emails/mime` | Send a MIME email (multipart/attachments) |
| `DELETE` | `/api/emails/{id}` | Delete an email |
| `POST` | `/api/emails/{id}/read` | Mark email as read |
| `POST` | `/api/emails/{id}/star` | Toggle starred status |
| `POST` | `/api/emails/{id}/move` | Move email to a different folder |
| `GET` | `/api/emails/{id}/delivery-status` | Check outbound delivery status |

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

### Inbound Webhook (no auth required)

| Method | Path | Description |
|--------|-------|-------------|
| `POST` | `/inbound` | Receive inbound email from SMTP2GO/Cloudflare |

**Inbound webhook fields:** `from` (or `from_address`/`sender`), `to` (or `rcpt`/`recipient`), `subject` (or `subjects`), `text` (or `body`), `html`, `sender_ip` (or `srchost`), `mail` (or `raw_email` for Base64-encoded MIME). Supports `application/x-www-form-urlencoded`, `multipart/form-data`, and `application/json`.

## Move Email Example

```bash
curl -X POST http://192.168.4.41:5003/api/emails/123/move \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"folder_id": 137}'
```

## Folder Operations Example

```bash
# List folders
curl http://192.168.4.41:5003/api/folders \
  -H "Authorization: Bearer <token>"

# Create a folder
curl -X POST http://192.168.4.41:5003/api/folders \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "Processed"}'
```

## Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `EMAIL_SERVER` | Mail server base URL | `http://192.168.4.41:5003` |
| `EMAIL_ADDRESS` | Sender/recipient email | `evie@example.com` |
| `EMAIL_PASSWORD` | Account password | `your_password` |
| `EMAIL_TO` | Default recipient for send | `user@example.com` |

## Operational Notes

- Search by subject first for fast retrieval of API keys or reports
- Avoid dumping full HTML email bodies unless needed
- When sending mail for tests, prefer small plain-text messages
- The server stores inbound mail in PostgreSQL; outbound is relayed via SMTP
- Inbound webhook (`POST /inbound`) requires no auth — called by SMTP2GO/Cloudflare Email Workers
- Base64-encoded MIME content in `raw_email`/`mail` fields is auto-decoded
- When `text`/`html` are empty, body content is extracted from raw MIME