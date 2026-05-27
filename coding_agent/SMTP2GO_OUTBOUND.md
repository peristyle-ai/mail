# SMTP2GO Outbound Relay — Implementation Plan

## Overview

py_pg_email currently delivers outbound email via **direct MX delivery**. This fails in most environments because Port 25 is blocked, residential IPs are on spam blocklists, and there is no authentication with receiving mail servers.

we would therefore like to add a configurable (by domain) feature to relay all outbound email through a configured SMTP provider (SMTP2GO, SendGrid, etc.) per domain.

a separate open source project will interface with new API routes to allow a user to configure the relay details. 
the new API routes will need to be documented in coding_agent/API_INTEGRATION_GUIDE.md and API_DOCUMENTATION.md however. 

---

## Architecture

```
User sends email via py_pg_email API
  → queued in outbound_emails table
    → OutboundQueueProcessor picks it up
      → looks up relay credentials from domains table (per-domain)
        → connects to relay provider (e.g. mail-au.smtp2go.com:2525 and if relay is configured for that domain)
          → relay provider delivers to recipient MX
```

**Each domain has its own SMTP relay credentials.** This allows:
- Multiple SMTP2GO accounts (one per domain/project) to stay under free tier limits
- Different relay providers per domain (smtp2go, sendgrid, etc.)
- Independent quota management per project

---

## Database Schema

### New `domains` Table

```sql
CREATE TABLE domains (
    id SERIAL PRIMARY KEY,
    domain VARCHAR(255) NOT NULL UNIQUE,

    -- Relay configuration
    relay_provider VARCHAR(50) DEFAULT 'smtp2go',  -- 'smtp2go', 'sendgrid', 'smtp', NULL=none
    relay_host VARCHAR(255),                         -- e.g. mail-au.smtp2go.com
    relay_port INTEGER DEFAULT 2525,
    relay_username VARCHAR(255),                     -- SMTP login
    relay_password_encrypted VARCHAR(500),            -- SMTP password (encrypt at rest)
    relay_from_address VARCHAR(255),                -- Verified FROM address for this domain

    -- Relay status
    relay_verified BOOLEAN DEFAULT FALSE,           -- Credentials confirmed working
    relay_verified_at TIMESTAMPTZ,

    -- DNS verification (DKIM/SPF status)
    spf_verified BOOLEAN DEFAULT FALSE,
    dkim_verified BOOLEAN DEFAULT FALSE,

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_domains_domain ON domains(domain);
CREATE INDEX idx_domains_relay_provider ON domains(relay_provider);
CREATE INDEX idx_domains_relay_verified ON domains(relay_verified);
```

### Example Initial Data

```sql
INSERT INTO domains (domain, relay_provider, relay_host, relay_port, relay_username, relay_from_address, relay_verified)
VALUES
    ('example.com.au', 'smtp2go', 'mail-au.smtp2go.com', 2525, 'example.com.au', 'support@example.com.au', TRUE),
    ('example.ai', 'smtp2go', 'mail-au.smtp2go.com', 2525, 'example.ai', 'hello@example.ai', TRUE)
ON CONFLICT (domain) DO NOTHING;
```

### Notes on Password Storage

`relay_password_encrypted` stores the SMTP password. Do not store as plain text.

---

## Implementation

### Step 1 — SMTP2GO Delivery Client

**File:** `smtp_server/outbound/smtp2go_delivery.py` (new file)

```python
"""
SMTP2GO Relay Delivery Client

Delivers emails through SMTP2GO relay instead of direct MX delivery.
Credentials are per-domain (looked up from domains table).
"""
import smtplib
import ssl
import logging
from email.message import EmailMessage
from typing import Tuple

logger = logging.getLogger(__name__)


class SMTP2GODelivery:
    """SMTP client for delivering emails via SMTP2GO relay."""

    def __init__(
        self,
        relay_host: str = "mail-au.smtp2go.com",
        relay_port: int = 2525,
        username: str = None,
        password: str = None,
        timeout: int = 30,
    ):
        self.relay_host = relay_host
        self.relay_port = relay_port
        self.username = username
        self.password = password
        self.timeout = timeout

    def deliver(
        self,
        from_address: str,
        to_addresses: list[str],
        message: EmailMessage,
    ) -> Tuple[bool, str]:
        """
        Deliver an email through the SMTP2GO relay.

        Args:
            from_address: Sender email (must be a verified domain in SMTP2GO)
            to_addresses: List of recipient email addresses
            message: EmailMessage object to send

        Returns:
            Tuple of (success: bool, message: str)
        """
        if not self.username or not self.password:
            return False, "SMTP relay credentials not configured"

        if isinstance(to_addresses, str):
            to_addresses = [to_addresses]

        try:
            logger.info(
                f"Relay: {from_address} -> {to_addresses} "
                f"via {self.relay_host}:{self.relay_port}"
            )

            ctx = ssl.create_default_context()
            ctx.check_hostname = True
            ctx.verify_mode = ssl.CERT_REQUIRED

            with smtplib.SMTP(self.relay_host, self.relay_port, timeout=self.timeout) as server:
                server.starttls(context=ctx)
                server.login(self.username, self.password)
                server.sendmail(from_address, to_addresses, message.as_bytes())

            logger.info(f"Relay success: {from_address} -> {to_addresses}")
            return True, "Delivered via relay"

        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"Relay auth failed: {e}")
            return False, f"Authentication failed: {e}"

        except smtplib.SMTPRecipientsRefused as e:
            logger.error(f"Relay recipient refused: {e}")
            return False, f"Recipient refused: {e}"

        except smtplib.SMTPSenderRefused as e:
            logger.error(f"Relay sender refused: {e}")
            return False, f"Sender refused — FROM address must be verified in relay account: {e}"

        except smtplib.SMTPServerDisconnected as e:
            logger.error(f"Relay disconnected: {e}")
            return False, f"Server disconnected: {e}"

        except smtplib.SMTPException as e:
            logger.error(f"Relay SMTP error: {e}")
            return False, f"SMTP error: {e}"

        except Exception as e:
            logger.error(f"Relay unexpected error: {e}")
            return False, f"Unexpected error: {e}"
```

### Step 2 — Update Queue Processor to Use Per-Domain Credentials

**File:** `smtp_server/outbound/queue_processor.py`

Modify `OutboundQueueProcessor` to look up relay credentials per-domain:

```python
from .smtp2go_delivery import SMTP2GODelivery

class OutboundQueueProcessor:
    def __init__(self, ...):
        # ... existing init ...


    def _get_domain_relay_config(self, domain: str) -> dict | None:
        """Look up relay credentials for a domain from the domains table.

        Returns:
            Dict with relay_host, relay_port, relay_username, relay_password_encrypted, relay_from_address
            or None if no relay is configured for this domain.
        """
        import re
        # Extract domain from email address
        if '@' in domain:
            domain = domain.split('@')[-1]

        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT relay_provider, relay_host, relay_port,
                       relay_username, relay_password_encrypted, relay_from_address,
                       relay_verified
                FROM domains
                WHERE domain = %s AND relay_provider IS NOT NULL
            """, (domain,))
            row = cursor.fetchone()
            if not row:
                return None
            # Handle both tuple (plain cursor) and dict (RealDictCursor)
            if isinstance(row, dict):
                return {
                    'relay_provider': row.get('relay_provider'),
                    'relay_host': row.get('relay_host'),
                    'relay_port': row.get('relay_port') or 2525,
                    'relay_username': row.get('relay_username'),
                    'relay_password': row.get('relay_password_encrypted'),
                    'relay_from_address': row.get('relay_from_address'),
                    'relay_verified': row.get('relay_verified', False),
                }
            else:
                return {
                    'relay_provider': row[0],
                    'relay_host': row[1],
                    'relay_port': row[2] or 2525,
                    'relay_username': row[3],
                    'relay_password': row[4],
                    'relay_from_address': row[5],
                    'relay_verified': row[6] or False,
                }
        finally:
            cursor.close()
            conn.close()

    def _deliver_email(self, email: dict, queue_item: dict) -> Tuple[bool, str]:
        """
        Deliver a single email. Looks up per-domain relay credentials.

        If the domain has relay credentials in the domains table, uses those.
        Otherwise falls back to direct MX delivery.
        """
        from_address = queue_item['from_address']
        to_addresses = [queue_item['to_address']]

        # Extract domain from FROM address
        domain = from_address.split('@')[-1] if '@' in from_address else from_address
        relay_config = self._get_domain_relay_config(domain)

        if not relay_config or not relay_config.get('relay_username'):
            logger.info(f"No relay configured for {domain} — falling back to direct MX")
            return self._deliver_direct(email, to_addresses)

        # Deliver via configured relay
        username = relay_config['relay_username']
        password = relay_config['relay_password']
        host = relay_config['relay_host'] or self.default_host
        port = relay_config['relay_port'] or self.default_port

        if relay_config.get('relay_provider') == 'smtp2go':
            sender = SMTP2GODelivery(
                relay_host=host,
                relay_port=port,
                username=username,
                password=password,
            )
            return sender.deliver(from_address, to_addresses, email['message'])

        # Future: add SendGrid, Postmark, etc. handlers here
        # elif relay_config.get('relay_provider') == 'sendgrid':
        #     return sendgrid_deliver(...)

        logger.warning(f"Unknown relay provider: {relay_config.get('relay_provider')}")
        return self._deliver_direct(email, to_addresses)
```

### Step 3 — API Routes for Domain Relay Credentials

**File:** `app/routes/domains.py` (new file)

```python
"""
Domain Management Routes

Handles domain relay configuration (SMTP credentials, provider settings).
All routes require authentication.
"""
from flask import Blueprint, request, jsonify
from .auth import token_required

domains_bp = Blueprint('domains', __name__, url_prefix='/api/domains')


def _domain_to_dict(row) -> dict:
    """Convert a domain row (tuple or dict) to a clean dict."""
    if isinstance(row, dict):
        return {
            'id': row.get('id'),
            'domain': row.get('domain'),
            'relay_provider': row.get('relay_provider'),
            'relay_host': row.get('relay_host'),
            'relay_port': row.get('relay_port'),
            'relay_username': row.get('relay_username'),
            'relay_from_address': row.get('relay_from_address'),
            'relay_verified': row.get('relay_verified', False),
            'spf_verified': row.get('spf_verified', False),
            'dkim_verified': row.get('dkim_verified', False),
            'has_password': bool(row.get('relay_password_encrypted')),
        }
    # Tuple: (id, domain, relay_provider, relay_host, relay_port,
    #         relay_username, relay_password_encrypted, relay_from_address,
    #         relay_verified, spf_verified, dkim_verified, ...)
    return {
        'id': row[0],
        'domain': row[1],
        'relay_provider': row[2],
        'relay_host': row[3],
        'relay_port': row[4],
        'relay_username': row[5],
        'relay_from_address': row[7],
        'relay_verified': bool(row[8]) if len(row) > 8 else False,
        'spf_verified': bool(row[9]) if len(row) > 9 else False,
        'dkim_verified': bool(row[10]) if len(row) > 10 else False,
        'has_password': bool(row[6]) if len(row) > 6 else False,
    }


@domains_bp.route('', methods=['GET'])
@token_required
def list_domains():
    """List all domains for the current user's account.

    Returns domains with relay configuration (password redacted).
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT id, domain, relay_provider, relay_host, relay_port,
                   relay_username, relay_password_encrypted, relay_from_address,
                   relay_verified, spf_verified, dkim_verified,
                   created_at, updated_at
            FROM domains
            ORDER BY domain ASC
        """)
        rows = cursor.fetchall()
        return jsonify({
            'domains': [_domain_to_dict(r) for r in rows]
        })
    finally:
        cursor.close()
        conn.close()


@domains_bp.route('/<domain>', methods=['GET'])
@token_required
def get_domain(domain: str):
    """Get relay configuration for a specific domain."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT id, domain, relay_provider, relay_host, relay_port,
                   relay_username, relay_password_encrypted, relay_from_address,
                   relay_verified, spf_verified, dkim_verified,
                   created_at, updated_at
            FROM domains WHERE domain = %s
        """, (domain,))
        row = cursor.fetchone()
        if not row:
            return jsonify({'error': 'Domain not found'}), 404
        return jsonify(_domain_to_dict(row))
    finally:
        cursor.close()
        conn.close()


@domains_bp.route('/<domain>/relay', methods=['PUT'])
@token_required
def set_domain_relay(domain: str):
    """
    Set or update relay credentials for a domain.

    Body (JSON):
        relay_provider: str  -- 'smtp2go', 'sendgrid', 'smtp'
        relay_host: str       -- e.g. mail-au.smtp2go.com
        relay_port: int      -- e.g. 2525
        relay_username: str   -- SMTP login
        relay_password: str    -- SMTP password (stored encrypted)
        relay_from_address: str  -- Verified FROM address for this domain

    Returns:
        Updated domain config (password redacted)
    """
    data = request.get_json() or {}
    provider = data.get('relay_provider', '').strip()
    host = data.get('relay_host', '').strip()
    port = data.get('relay_port')
    username = data.get('relay_username', '').strip()
    password = data.get('relay_password', '').strip()
    from_address = data.get('relay_from_address', '').strip()

    if not provider or not username or not password:
        return jsonify({'error': 'relay_provider, relay_username, and relay_password are required'}), 400

    if not host:
        # Default SMTP2GO host
        host = 'mail-au.smtp2go.com' if provider == 'smtp2go' else ''

    port = port or (2525 if provider == 'smtp2go' else 587)

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO domains
              (domain, relay_provider, relay_host, relay_port,
               relay_username, relay_password_encrypted, relay_from_address,
               relay_verified, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE, NOW())
            ON CONFLICT (domain) DO UPDATE SET
              relay_provider = EXCLUDED.relay_provider,
              relay_host = EXCLUDED.relay_host,
              relay_port = EXCLUDED.relay_port,
              relay_username = EXCLUDED.relay_username,
              relay_password_encrypted = EXCLUDED.relay_password_encrypted,
              relay_from_address = EXCLUDED.relay_from_address,
              relay_verified = FALSE,
              updated_at = NOW()
            RETURNING id
        """, (domain, provider, host, port, username, password, from_address))

        row = cursor.fetchone()
        conn.commit()

        return jsonify({
            'success': True,
            'domain': domain,
            'relay_provider': provider,
            'relay_host': host,
            'relay_port': port,
            'relay_username': username,
            'relay_from_address': from_address,
            'relay_verified': False,
            'message': 'Relay credentials saved. Call /relay/verify to confirm they work.'
        })

    finally:
        cursor.close()
        conn.close()


@domains_bp.route('/<domain>/relay/verify', methods=['POST'])
@token_required
def verify_domain_relay(domain: str):
    """
    Test relay credentials by attempting to connect and login.
    Does NOT send an email — just verifies the connection works.
    """
    from smtp_server.outbound.smtp2go_delivery import SMTP2GODelivery

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT relay_provider, relay_host, relay_port,
                   relay_username, relay_password_encrypted, relay_from_address
            FROM domains WHERE domain = %s
        """, (domain,))
        row = cursor.fetchone()

        if not row:
            return jsonify({'error': 'Domain not found'}), 404

        # Handle both tuple and dict
        if isinstance(row, dict):
            provider = row.get('relay_provider')
            host = row.get('relay_host')
            port = row.get('relay_port')
            username = row.get('relay_username')
            password = row.get('relay_password_encrypted')
        else:
            provider, host, port, username, password = row[0], row[1], row[2], row[3], row[4]

        if not username or not password:
            return jsonify({'error': 'No relay credentials configured for this domain'}), 400

        if provider == 'smtp2go':
            sender = SMTP2GODelivery(
                relay_host=host or 'mail-au.smtp2go.com',
                relay_port=port or 2525,
                username=username,
                password=password,
            )
            # Quick connect+login test (don't send)
            import smtplib, ssl
            try:
                ctx = ssl.create_default_context()
                with smtplib.SMTP(host or 'mail-au.smtp2go.com', port or 2525, timeout=15) as s:
                    s.starttls(context=ctx)
                    s.login(username, password)
                verified = True
            except Exception as e:
                return jsonify({
                    'success': False,
                    'error': f'Connection failed: {e}'
                }), 400

        else:
            return jsonify({'error': f'Provider {provider} verify not implemented yet'}), 501

        if verified:
            cursor.execute("""
                UPDATE domains SET relay_verified = TRUE, relay_verified_at = NOW()
                WHERE domain = %s
            """, (domain,))
            conn.commit()

        return jsonify({
            'success': True,
            'domain': domain,
            'relay_verified': True,
            'message': 'Relay credentials verified successfully'
        })

    finally:
        cursor.close()
        conn.close()


@domains_bp.route('/<domain>/relay', methods=['DELETE'])
@token_required
def delete_domain_relay(domain: str):
    """Remove relay configuration for a domain (keeps the domain record)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE domains SET
                relay_provider = NULL,
                relay_host = NULL,
                relay_port = NULL,
                relay_username = NULL,
                relay_password_encrypted = NULL,
                relay_from_address = NULL,
                relay_verified = FALSE,
                updated_at = NOW()
            WHERE domain = %s
            RETURNING id
        """, (domain,))
        row = cursor.fetchone()
        conn.commit()

        if not row:
            return jsonify({'error': 'Domain not found'}), 404

        return jsonify({'success': True, 'domain': domain, 'message': 'Relay credentials removed'})

    finally:
        cursor.close()
        conn.close()
```

### Step 4 — Register the Blueprint

**File:** `app/__init__.py` (or wherever blueprints are registered)

```python
from app.routes.domains import domains_bp

def create_app():
    app = Flask(__name__)
    # ... existing setup ...
    app.register_blueprint(domains_bp)
    return app
```

### Step 5 — Update `start_servers.py`

Add domains table creation on startup:

```python
def ensure_tables():
    """Create tables if they don't exist."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS domains (
            id SERIAL PRIMARY KEY,
            domain VARCHAR(255) NOT NULL UNIQUE,
            relay_provider VARCHAR(50),
            relay_host VARCHAR(255),
            relay_port INTEGER DEFAULT 2525,
            relay_username VARCHAR(255),
            relay_password_encrypted VARCHAR(500),
            relay_from_address VARCHAR(255),
            relay_verified BOOLEAN DEFAULT FALSE,
            relay_verified_at TIMESTAMPTZ,
            spf_verified BOOLEAN DEFAULT FALSE,
            dkim_verified BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    conn.commit()
    cursor.close()
    conn.close()
```

---

## API Routes Summary

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/domains` | ✅ JWT | List all domains and their relay config |
| GET | `/api/domains/<domain>` | ✅ JWT | Get relay config for one domain |
| PUT | `/api/domains/<domain>/relay` | ✅ JWT | Set/update relay credentials |
| POST | `/api/domains/<domain>/relay/verify` | ✅ JWT | Test relay credentials |
| DELETE | `/api/domains/<domain>/relay` | ✅ JWT | Remove relay config |

---

## Testing Plan

### Test 1 — Set relay credentials for a domain

```bash
TOKEN=$(curl -s -X POST http://localhost:5003/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"the operator@example.com.au","password":"password123"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

curl -X PUT http://localhost:5003/api/domains/example.com.au/relay \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "relay_provider": "smtp2go",
    "relay_host": "mail-au.smtp2go.com",
    "relay_port": 2525,
    "relay_username": "example.com.au",
    "relay_password": "sueXJ5l5JSXmBwNc",
    "relay_from_address": "support@example.com.au"
  }'
```

### Test 2 — Verify credentials

```bash
curl -X POST http://localhost:5003/api/domains/example.com.au/relay/verify \
  -H "Authorization: Bearer $TOKEN"
```

### Test 3 — Send email via API (should use SMTP2GO relay)

```bash
curl -X POST http://localhost:5003/api/emails/send \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "to": "the operator@example.com.au",
    "subject": "Relay Test",
    "text": "Sent via SMTP2GO relay"
  }'
```

---

## Files to Create/Modify

| File | Action |
|------|--------|
| `app/routes/domains.py` | **Create** — domain relay credential management API |
| `app/__init__.py` | **Modify** — register `domains_bp` blueprint |
| `smtp_server/outbound/smtp2go_delivery.py` | **Create** — SMTP2GO relay client |
| `smtp_server/outbound/queue_processor.py` | **Modify** — look up per-domain credentials from domains table |
| `start_servers.py` | **Modify** — ensure domains table exists on startup |
| `config.yaml` | **Modify** — add relay defaults |

---

## Out of Scope

- **Provider-specific SDKs** — only SMTP2GO via generic SMTP for now. Other providers (SendGrid, Postmark) can be added as separate delivery classes.
- **Automatic DKIM/SPF verification** — domain verification done manually in SMTP2GO dashboard.
- **Relay quota tracking** — SMTP2GO's own dashboard handles quota monitoring.

---

## Key Constraints

1. **FROM address must match a verified domain in the relay account.** SMTP2GO rejects FROM addresses from unverified domains.

2. **TLS required for SMTP2GO.** Port 2525 with STARTTLS. Port 587 also works with TLS.

3. **Per-domain isolation.** Each domain's relay credentials are independent — one domain's quota exhaustion doesn't affect others.

4. **relay_verified = FALSE after any credential change.** Call `/relay/verify` after updating credentials to confirm they work.
