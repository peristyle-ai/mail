# Outbound Email Relay Implementation Plan

## Overview
Expand the mail server to support **outbound email delivery** to external SMTP servers. This enables the server to:
1. Accept emails from local users via API/SMTP
2. Deliver them to external recipients (Gmail, Outlook, etc.)
3. Handle retries, bounces, and delivery tracking
4. Maintain a "Sent" folder for users

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    OUTBOUND EMAIL FLOW                             │
└─────────────────────────────────────────────────────────────────┘

1. User sends email via API/SMTP
   ↓
2. Email stored in database with 'outbound' status
   ↓
3. Outbound Queue Processor picks up email
   ↓
4. MX Lookup: Find recipient's mail server
   ↓
5. SMTP Delivery: Connect and send email
   ↓
6. Update delivery status (success/bounced/retry)
   ↓
7. Move to Sent folder (or retry later)
```

## Components to Build

### 1. Database Schema Updates

```sql
-- Outbound email queue
CREATE TABLE outbound_queue (
    id SERIAL PRIMARY KEY,
    email_id INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
    recipient_email VARCHAR(255) NOT NULL,
    recipient_domain VARCHAR(255) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending, sending, sent, bounced, failed
    attempt_count INTEGER DEFAULT 0,
    last_attempt TIMESTAMP WITH TIME ZONE,
    next_attempt TIMESTAMP WITH TIME ZONE,
    error_message TEXT,
    delivered_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Delivery logs
CREATE TABLE delivery_logs (
    id SERIAL PRIMARY KEY,
    outbound_queue_id INTEGER REFERENCES outbound_queue(id),
    email_id INTEGER NOT NULL REFERENCES emails(id),
    recipient_email VARCHAR(255) NOT NULL,
    event_type VARCHAR(20) NOT NULL, -- attempt, success, bounce, failure
    smtp_response TEXT,
    error_message TEXT,
    remote_server VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX idx_outbound_status ON outbound_queue(status);
CREATE INDEX idx_outbound_next_attempt ON outbound_queue(next_attempt);
CREATE INDEX idx_outbound_domain ON outbound_queue(recipient_domain);
CREATE INDEX idx_delivery_logs_email ON delivery_logs(email_id);
```

### 2. MX Record Lookup Module

**File:** `smtp_server/outbound/mx_lookup.py`

**Responsibilities:**
- Query DNS for MX records
- Fallback to A record if no MX
- Cache results for performance
- Handle IPv4/IPv6 addresses

**Key Functions:**
```python
def get_mx_records(domain: str) -> List[Tuple[int, str]]:
    """Get MX records sorted by priority."""
    
def get_mail_server(domain: str) -> Optional[str]:
    """Get best mail server for domain."""
```

### 3. Outbound SMTP Delivery Client

**File:** `smtp_server/outbound/delivery.py`

**Responsibilities:**
- Connect to external SMTP servers
- Deliver emails using standard SMTP
- Handle TLS/SSL encryption
- Manage connection timeouts
- Parse SMTP responses

**Key Class:**
```python
class OutboundSMTPSender:
    def __init__(self, timeout=30, max_size=25*1024*1024):
        self.timeout = timeout
        self.max_size = max_size
    
    def deliver_email(
        self,
        from_address: str,
        to_address: str,
        message: EmailMessage,
        mail_server: str,
        port: int = 25
    ) -> Tuple[bool, str]:
        """Deliver email to remote server."""
```

### 4. Outbound Queue Processor

**File:** `smtp_server/outbound/queue_processor.py`

**Responsibilities:**
- Process pending emails from queue
- Coordinate MX lookup + SMTP delivery
- Manage retry logic with exponential backoff
- Update delivery status
- Run as background thread

**Key Class:**
```python
class OutboundQueueProcessor:
    def __init__(self, check_interval=30, max_retries=5):
        self.check_interval = check_interval
        self.max_retries = max_retries
    
    def start(self):
        """Start background processing thread."""
    
    def process_email(self, queue_id: int):
        """Process single outbound email."""
    
    def schedule_retry(self, queue_id: int, attempt: int):
        """Schedule next retry with exponential backoff."""
```

### 5. Email Storage Updates

**File:** `smtp_server/outbound/storage.py`

**Responsibilities:**
- Create "Sent" folder for users
- Queue outgoing emails for delivery
- Store delivery status
- Log delivery attempts

**Key Functions:**
```python
def queue_outbound_email(
    sender_id: int,
    from_address: str,
    to_addresses: List[str],
    subject: str,
    body: str,
    headers: dict
) -> int:
    """Queue email for outbound delivery."""

def get_delivery_status(email_id: int) -> dict:
    """Get delivery status for an email."""
```

### 6. Rate Limiting for Outbound

**File:** `smtp_server/outbound/rate_limiter.py`

**Responsibilities:**
- Limit emails per domain
- Limit emails per hour overall
- Prevent abuse and blacklisting

**Settings:**
```python
MAX_EMAILS_PER_DOMAIN_PER_MINUTE = 30
MAX_EMAILS_PER_HOUR = 100
MAX_CONNECTIONS_PER_DOMAIN = 5
```

### 7. API Endpoints

**File:** `app/routes/emails.py` (additions)

**New Endpoints:**
```python
@bp.route('/api/emails', methods=['POST'])
def send_email():
    """Send email (stores in queue for outbound delivery)."""

@bp.route('/api/emails/sent', methods=['GET'])
def get_sent_emails():
    """Get user's sent emails."""

@bp.route('/api/emails/<int:id>/delivery-status', methods=['GET'])
def get_delivery_status(id):
    """Get delivery status for outbound email."""
```

### 8. Configuration Updates

**Add to config.yaml:**
```yaml
outbound:
  enabled: true
  check_interval: 30  # seconds
  max_retries: 5
  retry_delays: [300, 900, 1800, 3600, 7200]  # 5min, 15min, 30min, 1hr, 2hr
  rate_limit_per_domain: 30  # per minute
  max_email_size: 26214400  # 25MB
  timeout: 30  # seconds
  
  # TLS settings for outbound
  tls_required: true
  tls_verify_cert: true
  
  # Bounce handling
  bounce_address: "bounces@example.com.au"
```

## Implementation Steps

### Phase 1: Database & Schema (15 min)
1. Add outbound_queue table
2. Add delivery_logs table
3. Create indexes
4. Run migration

### Phase 2: Core Modules (30 min)
1. Implement MX lookup module
2. Implement outbound SMTP client
3. Implement queue storage functions

### Phase 3: Queue Processor (30 min)
1. Build queue processor class
2. Add retry logic with exponential backoff
3. Integrate with start_servers.py

### Phase 4: Integration (20 min)
1. Update email creation API to handle outbound
2. Add delivery status endpoint
3. Create Sent folder logic

### Phase 5: Tests (25 min)
1. MX lookup tests (mock DNS)
2. SMTP delivery tests (mock server)
3. Queue processor tests
4. End-to-end integration tests

### Phase 6: Verification (10 min)
1. Test sending to Gmail
2. Test retry logic
3. Verify delivery tracking
4. Check rate limiting

## Testing Strategy

### Unit Tests
```python
# test_mx_lookup.py
- Test MX record query
- Test fallback to A record
- Test no MX record handling
- Test invalid domain

# test_outbound_smtp.py  
- Test SMTP connection
- Test TLS handshake
- Test email delivery success
- Test delivery failure handling
- Test timeout handling

# test_queue_processor.py
- Test queue processing
- Test retry scheduling
- Test max retries exceeded
- Test exponential backoff
```

### Integration Tests
```python
# test_outbound_integration.py
- Test end-to-end email sending
- Test delivery to real domain
- Test bounce handling
- Test rate limiting enforcement
```

### Manual Testing
1. Send email to Gmail
2. Verify it arrives in inbox
3. Check delivery status in API
4. Test retry after temporary failure
5. Check logs for delivery attempts

## Success Criteria

- ✅ Outbound emails queued immediately
- ✅ MX records resolved correctly
- ✅ Emails delivered to external servers
- ✅ Delivery status tracked accurately
- ✅ Retries work with exponential backoff
- ✅ Rate limiting prevents abuse
- ✅ All tests pass (15+ new tests)
- ✅ Gmail/Outlook delivery verified

## Files to Create/Modify

**New Files:**
- `smtp_server/outbound/__init__.py`
- `smtp_server/outbound/mx_lookup.py`
- `smtp_server/outbound/delivery.py`
- `smtp_server/outbound/queue_processor.py`
- `smtp_server/outbound/storage.py`
- `smtp_server/outbound/rate_limiter.py`
- `db/outbound_migration.sql`
- `tests/test_outbound_mx.py`
- `tests/test_outbound_smtp.py`
- `tests/test_outbound_queue.py`
- `tests/test_outbound_integration.py`

**Modified Files:**
- `db/schema.sql` - Add new tables
- `app/routes/emails.py` - Add outbound endpoints
- `smtp_server/handler.py` - Handle outgoing emails
- `start_servers.py` - Start queue processor
- `requirements.txt` - Add if needed
- `config.yaml` - Add outbound settings

## Time Estimate
**Total: ~2 hours**

## Risk Mitigation

1. **Rate Limiting** - Essential to prevent IP blacklisting
2. **Retry Logic** - Must handle temporary failures gracefully
3. **Bounce Handling** - Need to process bounces properly
4. **Queue Persistence** - Emails survive server restarts
5. **Security** - TLS required, no open relay

## Notes

- Start with basic delivery, add DKIM/SPF signing later
- Monitor for bounces and update reputation
- Consider using external SMTP relay (AWS SES, SendGrid) as fallback
- Log all delivery attempts for debugging
