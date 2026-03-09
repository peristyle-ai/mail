# Sender Blocklist Implementation Guide for py_pg_email

## Overview

Add a sender blocklist to the mail server so that emails from blocked senders/domains are rejected at the SMTP level and never stored in the database.

**Architecture**: The email client (`py_pg_client`) relies entirely on the mail server's blocklist API. The server is the single source of truth - the client does not maintain a local blocklist.

```
User blocks sender → Client calls API → Server stores in DB → SMTP rejects future emails
                       ↓
Client displays blocklist → API returns entries ← Server DB
```

## Database Changes

### New Table: `sender_blocklist`

Add to `db/schema.sql`:

```sql
-- Sender Blocklist Table
-- Blocks specific email addresses or entire domains
CREATE TABLE sender_blocklist (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255),              -- Specific email to block (nullable)
    domain VARCHAR(255),             -- Domain to block (nullable)
    source VARCHAR(50) DEFAULT 'manual',  -- 'manual', 'spam_report', etc.
    blocked_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    blocked_by INTEGER REFERENCES users(id),
    notes TEXT,
    CONSTRAINT check_block_target CHECK (email IS NOT NULL OR domain IS NOT NULL)
);

CREATE UNIQUE INDEX idx_sender_blocklist_email ON sender_blocklist(email) WHERE email IS NOT NULL;
CREATE UNIQUE INDEX idx_sender_blocklist_domain ON sender_blocklist(domain) WHERE email IS NULL AND domain IS NOT NULL;
```

### Migration Script

Create `db/add_sender_blocklist.sql`:

```sql
-- Migration: Add sender blocklist
CREATE TABLE IF NOT EXISTS sender_blocklist (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255),
    domain VARCHAR(255),
    source VARCHAR(50) DEFAULT 'manual',
    blocked_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    blocked_by INTEGER REFERENCES users(id),
    notes TEXT,
    CONSTRAINT check_block_target CHECK (email IS NOT NULL OR domain IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sender_blocklist_email ON sender_blocklist(email) WHERE email IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_sender_blocklist_domain ON sender_blocklist(domain) WHERE email IS NULL AND domain IS NOT NULL;
```

## API Endpoints

### Add to `app/routes/blacklist.py`

```python
# Sender Blocklist Endpoints

@blacklist_bp.route('/sender', methods=['GET'])
@require_auth
def list_sender_blocklist():
    """List all blocked senders/domains"""
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 50, type=int)
    offset = (page - 1) * limit
    
    conn = get_db()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute("""
        SELECT sb.*, u.email as blocked_by_email
        FROM sender_blocklist sb
        LEFT JOIN users u ON sb.blocked_by = u.id
        ORDER BY sb.blocked_at DESC
        LIMIT %s OFFSET %s
    """, (limit, offset))
    
    entries = cursor.fetchall()
    
    cursor.execute("SELECT COUNT(*) FROM sender_blocklist")
    total = cursor.fetchone()['count']
    
    cursor.close()
    
    return jsonify({
        'entries': [dict(e) for e in entries],
        'total': total,
        'page': page
    })
    
# Each entry contains: id, email, domain, source, blocked_at, blocked_by, notes
# Example: {"id": 1, "email": "spam@example.com", "domain": "example.com", "blocked_at": "2026-02-27T21:00:00+10:00"}


@blacklist_bp.route('/sender', methods=['POST'])
@require_auth
def add_sender_block():
    """Block a sender email or domain"""
    data = request.get_json()
    email = data.get('email', '').strip().lower() if data.get('email') else None
    domain = data.get('domain', '').strip().lower() if data.get('domain') else None
    notes = data.get('notes', '')
    
    if not email and not domain:
        return jsonify({'error': 'Email or domain required'}), 400
    
    user_id = g.user['id']
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        if email:
            # Extract domain from email if provided
            if '@' in email:
                email_domain = email.split('@')[-1]
            else:
                email_domain = None
            
            cursor.execute("""
                INSERT INTO sender_blocklist (email, domain, blocked_by, notes)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (email) DO NOTHING
                RETURNING id
            """, (email, email_domain, user_id, notes))
        else:
            cursor.execute("""
                INSERT INTO sender_blocklist (domain, blocked_by, notes)
                VALUES (%s, %s, %s)
                ON CONFLICT (domain) WHERE email IS NULL DO NOTHING
                RETURNING id
            """, (domain, user_id, notes))
        
        result = cursor.fetchone()
        conn.commit()
        
        if result:
            return jsonify({'success': True, 'id': result[0]}), 201
        else:
            return jsonify({'success': True, 'message': 'Already blocked'}), 200
            
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()


@blacklist_bp.route('/sender/<int:block_id>', methods=['DELETE'])
@require_auth
def remove_sender_block(block_id):
    """Remove a sender from the blocklist"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM sender_blocklist WHERE id = %s RETURNING id", (block_id,))
    result = cursor.fetchone()
    conn.commit()
    cursor.close()
    
    if result:
        return jsonify({'success': True})
    else:
        return jsonify({'error': 'Not found'}), 404


@blacklist_bp.route('/sender/check', methods=['GET'])
def check_sender_blocked():
    """Check if a sender email is blocked"""
    email = request.args.get('email', '').strip().lower()
    
    if not email:
        return jsonify({'error': 'Email required'}), 400
    
    domain = email.split('@')[-1] if '@' in email else None
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Check both specific email and domain
    cursor.execute("""
        SELECT id, email, domain FROM sender_blocklist
        WHERE email = %s OR (domain = %s AND email IS NULL)
        LIMIT 1
    """, (email, domain))
    
    result = cursor.fetchone()
    cursor.close()
    
    return jsonify({
        'blocked': result is not None,
        'email': email,
        'domain': domain,
        'block_type': 'email' if result and result[1] else 'domain' if result else None
    })
```

## SMTP Server Modifications

### Add to `smtp_server/handlers.py`

Create a function to check if sender is blocked:

```python
def is_sender_blocked(sender_email):
    """Check if sender is in the blocklist"""
    if not sender_email:
        return False
    
    sender_email = sender_email.lower().strip('<>')
    domain = sender_email.split('@')[-1] if '@' in sender_email else None
    
    import psycopg2
    from psycopg2.extras import RealDictCursor
    from config import Config
    
    try:
        conn = psycopg2.connect(Config.DATABASE_URL)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id FROM sender_blocklist
            WHERE email = %s OR (domain = %s AND email IS NULL)
            LIMIT 1
        """, (sender_email, domain))
        
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        
        return result is not None
    except Exception as e:
        print(f"Error checking blocklist: {e}")
        return False  # Allow on error
```

### Modify `smtp_server/server.py`

In the `handle_MAIL` or `process_message` function, add a check:

```python
# After extracting sender, before storing email:

if is_sender_blocked(sender):
    print(f"Rejected email from blocked sender: {sender}")
    return  # Don't store the email
```

Or if using `smtpd.SMTPServer`, override `process_message`:

```python
def process_message(self, peer, mailfrom, rcpttos, data, **kwargs):
    # Check if sender is blocked
    if is_sender_blocked(mailfrom):
        print(f"Rejected email from blocked sender: {mailfrom}")
        return  # Reject silently
    
    # Continue with normal processing
    # ... existing code ...
```

## Client Integration

The email client (`py_pg_client`) should call these endpoints when blocking:

1. **Block email**: `POST /api/blacklist/sender` with `{"email": "spam@example.com"}`
2. **Block domain**: `POST /api/blacklist/sender` with `{"domain": "spamdomain.com"}`
3. **Unblock**: `DELETE /api/blacklist/sender/<id>`
4. **List blocked**: `GET /api/blacklist/sender`

## Testing

```bash
# Login
TOKEN=$(curl -s -X POST http://localhost:5003/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "the operator@example.com.au", "password": "not-a-real-password"}' | jq -r '.token')

# Block a sender
curl -X POST http://localhost:5003/api/blacklist/sender \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"email": "spam@spammer.com"}'

# Block a domain
curl -X POST http://localhost:5003/api/blacklist/sender \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"domain": "spamdomain.com"}'

# Check if blocked
curl "http://localhost:5003/api/blacklist/sender/check?email=test@spamdomain.com"

# List blocked senders
curl -H "Authorization: Bearer $TOKEN" http://localhost:5003/api/blacklist/sender
```

## Files to Modify in py_pg_email

| File | Change |
|------|--------|
| `db/schema.sql` | Add `sender_blocklist` table |
| `db/add_sender_blocklist.sql` | New migration file |
| `app/routes/blacklist.py` | Add sender blocklist endpoints |
| `smtp_server/server.py` | Add blocklist check before storing |
| `init_db.py` | Run migration |

## Notes

- Blocked emails are rejected silently at SMTP level (no bounce)
- Both specific emails and domains can be blocked
- The `source` field tracks how the block was added (manual, spam_report, etc.)
- Blocklist is checked on every incoming email
