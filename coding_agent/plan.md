## Phase 7: SMTP Security Suite - Rate Limiting, SPF, Greylisting, and TLS

## Overview
Implement comprehensive security measures before opening SMTP server to the internet.

## Security Components

### 1. Rate Limiting
**Purpose:** Prevent abuse, spam floods, and DoS attacks

**Implementation:**
- Track connections per IP address
- Limit concurrent connections per IP (max 10)
- Limit emails per minute per IP (max 30)
- Limit emails per hour per IP (max 100)
- Automatic IP blocking after repeated violations
- In-memory storage with automatic cleanup

**Files:**
- `smtp_server/security/rate_limiter.py` - Rate limiting logic
- Updates to `smtp_server/handler.py` - Integration

### 2. SPF (Sender Policy Framework) Validation
**Purpose:** Prevent email spoofing and verify sender authorization

**Implementation:**
- Parse sender domain from MAIL FROM
- Query DNS for SPF records
- Validate sending IP against SPF policy
- Handle SPF results: pass, fail, neutral, softfail, none
- Reject or flag emails that fail SPF hardfail
- Log SPF results for monitoring

**Files:**
- `smtp_server/security/spf_validator.py` - SPF checking logic
- Updates to `smtp_server/handler.py` - Integration

**Dependencies:**
- `pyspf` or `spflib` library for SPF validation
- DNS resolution (dnspython)

### 3. Greylisting
**Purpose:** Reduce spam by temporarily rejecting unknown senders

**Implementation:**
- Track triplets: (client_ip, sender, recipient)
- First-time senders: reject with temporary error (4xx)
- Legitimate servers retry after 5-15 minutes
- Spammers often don't retry
- Whitelist after successful delivery
- Automatic expiration of greylist entries (24 hours)

**Files:**
- `smtp_server/security/greylist.py` - Greylisting logic
- Updates to `smtp_server/handler.py` - Integration
- Database table for greylist tracking

### 4. TLS/SSL Encryption
**Purpose:** Encrypt SMTP traffic to prevent eavesdropping

**Implementation:**
- Support SMTPS (port 465) - TLS from start
- Support STARTTLS (port 587) - upgrade to TLS
- Self-signed certificate generation for testing
- Support for Let's Encrypt certificates
- Force TLS for authentication (optional)
- Graceful fallback to plaintext for legacy clients (optional)

**Files:**
- `smtp_server/security/tls_config.py` - TLS configuration
- Updates to `smtp_server/server.py` - TLS support
- Certificate generation scripts

**Dependencies:**
- `ssl` module (built-in)
- `cryptography` library for cert generation

## Database Schema Updates

### New Table: Greylist
```sql
CREATE TABLE greylist (
    id SERIAL PRIMARY KEY,
    client_ip INET NOT NULL,
    sender VARCHAR(255) NOT NULL,
    recipient VARCHAR(255) NOT NULL,
    first_seen TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    retry_count INTEGER DEFAULT 0,
    whitelisted BOOLEAN DEFAULT FALSE,
    UNIQUE(client_ip, sender, recipient)
);

CREATE INDEX idx_greylist_ip ON greylist(client_ip);
CREATE INDEX idx_greylist_whitelisted ON greylist(whitelisted);
```

### New Table: Rate Limit Log
```sql
CREATE TABLE rate_limit_violations (
    id SERIAL PRIMARY KEY,
    client_ip INET NOT NULL,
    violation_type VARCHAR(50) NOT NULL,
    count INTEGER DEFAULT 1,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_rate_violations_ip ON rate_limit_violations(client_ip);
CREATE INDEX idx_rate_violations_time ON rate_limit_violations(timestamp);
```

## Configuration

### Environment Variables
```
# Security Settings
SMTP_RATE_LIMIT_ENABLED=true
SMTP_RATE_LIMIT_MAX_CONNECTIONS=10
SMTP_RATE_LIMIT_MAX_EMAILS_PER_MINUTE=30
SMTP_RATE_LIMIT_MAX_EMAILS_PER_HOUR=100

SMTP_SPF_ENABLED=true
SMTP_SPF_REJECT_FAIL=true

SMTP_GREYLIST_ENABLED=true
SMTP_GREYLIST_DELAY_MINUTES=5
SMTP_GREYLIST_WHITELIST_DAYS=30

SMTP_TLS_ENABLED=true
SMTP_TLS_CERT_PATH=/path/to/cert.pem
SMTP_TLS_KEY_PATH=/path/to/key.pem
SMTP_TLS_FORCE=false
```

## Implementation Plan

### Step 1: Core Security Module Structure
- Create `smtp_server/security/__init__.py`
- Create base security manager class
- Create configuration handler

### Step 2: Rate Limiting
- Implement connection tracking per IP
- Implement rate limit checks
- Add enforcement to SMTP handler
- Add tests

### Step 3: SPF Validation
- Install pyspf/dnspython
- Implement SPF checking
- Add enforcement to SMTP handler
- Add tests

### Step 4: Greylisting
- Create database table
- Implement greylist logic
- Add enforcement to SMTP handler
- Add tests

### Step 5: TLS/SSL
- Generate self-signed certificate
- Implement TLS wrapper
- Update SMTP server to support STARTTLS
- Add tests

### Step 6: Integration
- Update `start_servers.py` with security options
- Create security configuration documentation
- Add comprehensive integration tests

### Step 7: Testing
- Test rate limiting with multiple connections
- Test SPF validation with various domains
- Test greylisting with first-time senders
- Test TLS encryption
- Test all security features together

## Files to Create/Modify

**New Files:**
1. `smtp_server/security/__init__.py`
2. `smtp_server/security/rate_limiter.py`
3. `smtp_server/security/spf_validator.py`
4. `smtp_server/security/greylist.py`
5. `smtp_server/security/tls_config.py`
6. `scripts/generate_tls_cert.py`
7. `SECURITY.md` - Security configuration guide

**Modified Files:**
1. `smtp_server/handler.py` - Add security checks
2. `smtp_server/server.py` - Add TLS support
3. `db/schema.sql` - Add greylist table
4. `requirements.txt` - Add security dependencies
5. `start_servers.py` - Add security configuration

## Success Criteria
- [ ] Rate limiting prevents abuse (tested with >30 emails/min)
- [ ] SPF validation correctly identifies spoofed emails
- [ ] Greylisting reduces spam (80% reduction target)
- [ ] TLS encryption works on ports 465/587
- [ ] All security features configurable via environment variables
- [ ] Tests pass for all security components
- [ ] Documentation complete

## Estimated Time
- Step 1-2 (Rate Limiting): 45 minutes
- Step 3 (SPF): 30 minutes
- Step 4 (Greylisting): 45 minutes
- Step 5 (TLS): 60 minutes
- Step 6-7 (Integration & Testing): 45 minutes
- **Total: ~3.5-4 hours**
