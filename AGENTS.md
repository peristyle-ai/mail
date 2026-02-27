# Agent Guidelines for py_pg_email

## Project Overview

This is a local mail server with a REST API for local email management without SMTP. It consists of:
- **Flask API** on port 5001 (`app/`)
- **SMTP Server** on port 2525 (`smtp_server/outbound/`)
- **PostgreSQL** database for storage

## Commands

### Running the Application

```bash
# Flask API only (development)
flask run

# Both Flask API + SMTP Server (recommended)
python start_servers.py

# Initialize database
python init_db.py
```

### Running Tests

```bash
# Ensure test database exists
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
│   │   └── blacklist.py
│   └── utils/               # Utility functions
│       ├── auth.py          # JWT, password hashing
│       ├── users.py         # User management
│       ├── emails.py
│       ├── folders.py
│       └── attachments.py
├── smtp_server/
│   └── outbound/            # SMTP client code
│       ├── delivery.py
│       ├── mx_lookup.py
│       ├── dkim_signer.py
│       ├── rate_limiter.py
│       ├── storage.py
│       └── queue_processor.py
├── tests/                   # Test suite
├── db/
│   ├── schema.sql
│   └── migrations/
├── requirements.txt
└── run.py
```

## Important Notes

- Ask user permission before using active git commands (push, pull, revert, reset)
- Never fetch and run executables from the internet without checking hash/checksum
- Maintain a todo list in `coding_agent/plan.md` for tracking work
- Do not use npx or npm (this is a Python project)
- Always use a virtual environment for pip installs: `python -m venv venv && source venv/bin/activate && pip install -r requirements.txt`
