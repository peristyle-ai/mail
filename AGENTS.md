# Agent Guidelines for py_pg_email

## Project Overview

This is a local mail server with a REST API for local email management without SMTP. It consists of:
- **Flask API** on port 5003 (`app/`)
- **SMTP Server** on port 2525 (`smtp_server/`)
- **Inbound Webhook** at `POST /inbound` (for SMTP2GO relay)
- **PostgreSQL** database for storage

## Commands

### Running the Application

```bash
# Run as systemd user service (recommended)
systemctl --user start mail-server
systemctl --user status mail-server

# Manual run (development)
python start_servers.py

# Initialize database
python init_db.py
```

### Running Tests

```bash
# Ensure test database exists (requires postgres user)
createdb mail_server_test

# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_auth.py -v

# Run a single test
pytest tests/test_auth.py::test_register_success -v

# Run with coverage
pytest --cov=app tests/
```

## Code Style Guidelines

### General Rules

- **Use tabs for indentation** in Python files (this is project convention)
- **Maximum line length**: 120 characters
- **Blank lines**: Two blank lines between top-level definitions, one between method definitions
- **Docstrings**: Use triple quotes for all public functions; include type hints

### Imports

```python
# Standard library first
import os
import logging
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Tuple, Optional, List, Dict, Any

# Third-party libraries
from flask import Blueprint, request, jsonify
import psycopg2

# Local application imports
from app.db import get_db_connection
from app.utils import get_user_by_email, create_user
```

- Group imports: stdlib, third-party, local
- Use absolute imports (e.g., `from app.routes import auth`)
- Avoid wildcard imports (`from app.db import *`)

### Type Hints

Use type hints for all function parameters and return values:

```python
def process_email(user_id: int, email_data: Dict[str, Any]) -> Optional[int]:
    cursor.execute('SELECT * FROM users WHERE id = %s', (user_id,))
    return cursor.fetchone()

def get_all_users() -> List[Dict[str, Any]]:
    ...
```

### Naming Conventions

- **Variables/functions**: `snake_case` (e.g., `get_user_by_email`, `password_hash`)
- **Classes**: `PascalCase` (e.g., `OutboundSMTPSender`, `EmailMessage`)
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `MAX_ATTACHMENT_SIZE`)
- **Private methods**: prefix with underscore (e.g., `_internal_method`)

### Error Handling

- Use specific exception types when possible
- Return consistent JSON error responses
- Log errors with appropriate level

```python
# Good pattern
try:
    result = some_operation()
except ValueError as e:
    logger.warning(f"Invalid value: {e}")
    return jsonify({'error': 'Invalid input'}), 400
except Exception as e:
    logger.error(f"Unexpected error: {e}")
    return jsonify({'error': 'Internal server error'}), 500
```

### Database Operations

- Use parameterized queries to prevent SQL injection
- Always close cursors and connections (use context managers or try/finally)
- Use transactions for multi-statement operations

```python
# Good pattern
conn = get_db_connection()
try:
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE id = %s', (user_id,))
    result = cursor.fetchone()
finally:
    cursor.close()
    conn.close()
```

### Route Patterns (Flask)

```python
from flask import Blueprint, request, jsonify
from app.utils.auth import token_required
from app.db import get_db_connection

bp = Blueprint('emails', __name__)

@bp.route('/api/emails', methods=['GET'])
@token_required
def list_emails():
    # Access current user via request.current_user
    user_id = request.current_user['id']
    # ... implementation
    return jsonify({'emails': []})
```

### Swagger Documentation

Document all API endpoints using flasgger docstrings (YAML format inside triple quotes).

### Security Guidelines

- Never commit secrets to git (use `.env` files)
- Always validate user input
- Use parameterized queries for all database operations
- Validate file uploads (type, size limits)
- Ensure users can only access their own data

### Testing Guidelines

- Test file naming: `test_<module>.py`
- Test class naming: `Test<ClassName>`
- Test function naming: `test_<description>`
- Use fixtures from `tests/conftest.py`
- Include security tests for all endpoints

## File Structure

```
.
├── app/
│   ├── __init__.py          # Flask app factory
│   ├── app.py               # App entry point
│   ├── db.py                # Database connection
│   ├── main_routes.py       # Main routes
│   ├── routes/              # API endpoints
│   │   ├── auth.py
│   │   ├── emails.py
│   │   ├── folders.py
│   │   ├── search.py
│   │   ├── attachments.py
│   │   ├── blacklist.py      # IP and sender blocklist
│   │   └── inbound.py        # SMTP2GO webhook receiver (POST /inbound)
│   └── utils/               # Utility functions
│       ├── auth.py          # JWT, password hashing
│       ├── users.py         # User management
│       ├── emails.py
│       ├── folders.py
│       └── attachments.py
├── smtp_server/             # SMTP server
│   ├── handler.py           # SMTP message handler
│   ├── email_storage.py     # Email storage to DB
│   ├── sender_blocklist_checker.py  # Check blocked senders
│   ├── blacklist_checker.py  # IP blacklist checks
│   ├── security.py           # Rate limiting, SPF, greylisting
│   └── outbound/            # Outbound delivery
│       ├── delivery.py
│       ├── mx_lookup.py
│       ├── dkim_signer.py
│       ├── rate_limiter.py
│       ├── storage.py
│       └── queue_processor.py
├── scripts/                  # Utility scripts
│   ├── backfill_html.py
│   └── backfill_sender_recipient.py
├── tests/                   # Test suite
├── db/
│   ├── schema.sql
│   └── migrations/
├── coding_agent/            # Agent instructions
├── systemd/user/             # User systemd service
├── start_servers.py          # Start both Flask + SMTP
├── init_db.py
└── requirements.txt
```

## Important Notes

- Ask user permission before using active git commands (push, pull, revert, reset)
- Never fetch and run executables from the internet without checking hash/checksum
- Maintain a todo list in `coding_agent/plan.md` for tracking work
- Do not use npx or npm (this is a Python project)
- Always use a virtual environment for pip installs: `python -m venv venv && source venv/bin/activate && pip install -r requirements.txt`

## Key Features

### Email Storage
- Emails have `sender_id` (actual sender) and `recipient_id` (recipient user)
- API returns `sender` and `recipient` as objects `{email, name}` (not flat fields)
- HTML emails have `body_html` field (mapped to `html` in API)
- Raw MIME content stored in `raw_email` column

### Email Access Control
- Email visibility is based on **folder ownership**: `JOIN folders f ON e.folder_id = f.id WHERE f.user_id = current_user_id`
- Users can only see/access emails in folders they own
- Local delivery creates separate copies: one in sender's Sent folder, one in recipient's Inbox
- All email endpoints (list, get, delete, move, star, mark read) use folder ownership for authorization

### Required Environment Variables
- `HOST`: Required. The IP address to bind to (e.g., `192.168.4.41`). Server fails to start without it.
- `DATABASE_URL`: PostgreSQL connection string
- `JWT_SECRET`: Secret key for JWT tokens
- `SMTP2GO_WEBHOOK_SECRET`: Optional. HMAC-SHA256 key for verifying SMTP2GO webhook signatures.

### Blocklist Features
- **IP Blacklist**: `/api/blacklist/ip/*` - block by IP address
- **Sender Blocklist**: `/api/blacklist/sender/*` - block specific emails or domains at SMTP level

### Inbound Webhook (SMTP2GO Relay)
- **Endpoint**: `POST /inbound` - no JWT auth required; called by SMTP2GO or similar relay services
- Accepts `application/x-www-form-urlencoded`, `multipart/form-data`, or `application/json`
- Fields: `from`, `to`, `subject`, `text`, `html`, `sender_ip`, `mail` (raw MIME)
- Checks sender blocklist before storing
- Creates sender user (is_local=FALSE) if not found
- Returns 200 with `{"status": "rejected"}` for unknown recipients (prevents SMTP2GO retries)
- Security: rate limiting (60/min per IP), email validation, header injection prevention, payload size limits, optional SMTP2GO HMAC signature verification
- Set `SMTP2GO_WEBHOOK_SECRET` env var to enable signature verification
