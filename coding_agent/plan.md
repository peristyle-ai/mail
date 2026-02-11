## Phase 6: Add SMTP Server for Receiving Real Emails

## Overview
Add SMTP server capability using aiosmtpd to receive real emails from the internet and store them in PostgreSQL.

## Architecture

### Components:
1. **SMTP Server** (aiosmtpd) - Receives emails on port 25/587
2. **Email Handler** - Parses incoming emails and stores in database
3. **Flask API** - Serves existing REST API for email management (port 5000)
4. **Test Scripts** - For testing from another computer

### Flow:
```
External Email Client/Sender
        |
        v
    Port 587 (SMTP)
        |
        v
   aiosmtpd Server
        |
        v
   Email Handler
        |
        v
   PostgreSQL Database
        |
        v
   Flask REST API (Port 5000)
```

## Implementation Steps

### Step 1: Install Dependencies
- Install aiosmtpd for SMTP server functionality
- Add to requirements.txt

### Step 2: Create SMTP Server Module
**Files to create:**
- `smtp_server/__init__.py` - Package initialization
- `smtp_server/handler.py` - SMTP message handler
- `smtp_server/server.py` - SMTP server setup
- `smtp_server/email_storage.py` - Store emails in database

### Step 3: Update Database Schema
- Add support for incoming email fields
- Store raw email headers
- Support multiple recipients

### Step 4: Create Test Script
- `scripts/send_test_email.py` - Script for other computer (192.168.4.x)
- Can send via SMTP to 192.168.4.30:587

### Step 5: Create Startup Script
- `start_servers.py` - Starts both Flask and SMTP servers
- Manage both processes

### Step 6: Network Configuration
- Document port forwarding for internet access
- Firewall configuration
- Testing from external sources

## Network Setup

### Local Network Test:
```
Flask Server: 192.168.4.30 (ports 5000, 587)
Test Computer: 192.168.4.x
```

### Ports:
- **5000**: Flask API (existing)
- **587**: SMTP Submission (new, for receiving emails)
- **25**: SMTP (optional, often blocked by ISPs)

### Port Forwarding for Internet:
1. Router: Forward external 587 → 192.168.4.30:587
2. Firewall: Allow incoming TCP on port 587
3. For production: Set up MX record in DNS

## Testing Plan

### Phase 1: Local Test
1. Start SMTP server on Flask machine
2. Send test email using script on same machine
3. Verify email appears in database
4. Verify email appears in API

### Phase 2: Network Test
1. Run test script from other computer (192.168.4.x)
2. Send email to the operator@example.com.au
3. Verify receipt in database

### Phase 3: Internet Test
1. Configure port forwarding
2. Send email from external service (Gmail, etc.)
3. Verify receipt

## Files to Create
1. `smtp_server/__init__.py`
2. `smtp_server/handler.py`
3. `smtp_server/server.py`
4. `smtp_server/email_storage.py`
5. `scripts/send_test_email.py`
6. `start_servers.py`
7. `SMTP_SETUP.md`

## Security Considerations
- No authentication needed for incoming (standard SMTP)
- Rate limiting to prevent spam
- Spam filtering (optional)
- TLS/SSL encryption (recommended for production)

## Estimated Time
- SMTP module: 40 minutes
- Database updates: 15 minutes
- Test scripts: 15 minutes
- Testing: 20 minutes
- **Total: ~90 minutes**
