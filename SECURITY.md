# Mail Server Security Guide

This guide covers the security features implemented in the mail server and how to configure them for production use.

## Security Features Overview

The mail server includes four primary security mechanisms:

1. **Rate Limiting** - Prevents abuse and DoS attacks
2. **SPF Validation** - Prevents email spoofing
3. **Greylisting** - Reduces spam from unknown senders
4. **TLS/SSL Encryption** - Secures SMTP connections

All features are configurable via environment variables.

## Quick Start

By default, all security features are **enabled** with safe defaults:

```bash
# Start with security enabled (default)
python start_servers.py

# View current security configuration
python -c "from smtp_server.security import security_config; print(security_config)"
```

## Configuration

### Environment Variables

All security settings can be configured via environment variables:

#### Rate Limiting
```bash
# Enable/disable rate limiting (default: true)
export SMTP_RATE_LIMIT_ENABLED=true

# Max concurrent connections per IP (default: 10)
export SMTP_RATE_LIMIT_MAX_CONNECTIONS=10

# Max emails per minute per IP (default: 30)
export SMTP_RATE_LIMIT_MAX_EMAILS_PER_MINUTE=30

# Max emails per hour per IP (default: 100)
export SMTP_RATE_LIMIT_MAX_EMAILS_PER_HOUR=100
```

#### SPF Validation
```bash
# Enable/disable SPF (default: true)
export SMTP_SPF_ENABLED=true

# Reject emails that fail SPF (default: true)
export SMTP_SPF_REJECT_FAIL=true
```

#### Greylisting
```bash
# Enable/disable greylisting (default: true)
export SMTP_GREYLIST_ENABLED=true

# Delay before accepting new senders in minutes (default: 5)
export SMTP_GREYLIST_DELAY_MINUTES=5

# How long to remember whitelisted senders in days (default: 30)
export SMTP_GREYLIST_WHITELIST_DAYS=30
```

#### TLS/SSL
```bash
# Enable/disable TLS (default: true)
export SMTP_TLS_ENABLED=true

# Path to TLS certificate
export SMTP_TLS_CERT_PATH=/path/to/cert.pem

# Path to TLS private key
export SMTP_TLS_CERT_KEY=/path/to/key.pem

# Force TLS for all connections (default: false)
export SMTP_TLS_FORCE=false
```

## Rate Limiting

### How It Works

- Tracks connections and emails per IP address
- Automatically blocks IPs that exceed limits
- Blocks last 30 minutes by default after violation
- In-memory storage (resets on server restart)

### Rate Limits

Default limits are set to handle legitimate use:
- **10 concurrent connections** - Most mail servers use 1-3
- **30 emails/minute** - Legitimate bulk mail is slower
- **100 emails/hour** - Spammers send much faster

### Adjusting for Your Needs

**Small personal server:**
```bash
export SMTP_RATE_LIMIT_MAX_CONNECTIONS=5
export SMTP_RATE_LIMIT_MAX_EMAILS_PER_MINUTE=10
export SMTP_RATE_LIMIT_MAX_EMAILS_PER_HOUR=50
```

**High-volume server:**
```bash
export SMTP_RATE_LIMIT_MAX_CONNECTIONS=20
export SMTP_RATE_LIMIT_MAX_EMAILS_PER_MINUTE=60
export SMTP_RATE_LIMIT_MAX_EMAILS_PER_HOUR=300
```

## SPF Validation

### What is SPF?

Sender Policy Framework (SPF) allows domain owners to specify which IP addresses are authorized to send email for their domain. It helps prevent email spoofing.

### How It Works

1. Sender connects to your server
2. Your server queries DNS for sender's SPF record
3. SPF record lists authorized IP addresses
4. If sender's IP is authorized → email accepted
5. If not authorized → email rejected (if `SPF_REJECT_FAIL=true`)

### Example SPF Results

```
user@example.com from 192.168.1.1:
  → SPF record: v=spf1 ip4:74.125.0.0/16 -all
  → 192.168.1.1 not in 74.125.0.0/16
  → Result: FAIL (email rejected)

sender@yourdomain.com from your.server.ip:
  → SPF record: v=spf1 ip4:your.server.ip -all
  → Server IP matches
  → Result: PASS (email accepted)
```

### Disabling SPF

If you want to accept all emails regardless of SPF:
```bash
export SMTP_SPF_ENABLED=false
```

Or keep enabled but don't reject failures:
```bash
export SMTP_SPF_REJECT_FAIL=false
```

## Greylisting

### What is Greylisting?

Greylisting temporarily rejects emails from unknown senders. Legitimate mail servers automatically retry after a delay (usually 5-15 minutes). Most spammers don't retry.

### How It Works

1. **First contact** from new (IP, sender, recipient) triplet:
   - Server responds: `450 Try again in 5 minutes`
   - Email is not delivered
   - Triplet is recorded in database

2. **Retry after delay** (5+ minutes):
   - Server recognizes triplet
   - Marks as whitelisted
   - Accepts email

3. **Future emails** from same triplet:
   - Immediately accepted
   - Whitelist lasts 30 days

### Effectiveness

Greylisting typically reduces spam by **70-90%** because:
- Most spam bots don't implement retry logic
- Legitimate mail servers (Gmail, Outlook, etc.) always retry
- Low false positive rate for real email

### Potential Issues

**Delay in first email:** New senders experience 5-minute delay

**Solutions:**
- Keep delay short (5 minutes is usually enough)
- Whitelist important domains manually
- Some users accept the small delay for spam reduction

### Disabling Greylisting

```bash
export SMTP_GREYLIST_ENABLED=false
```

## TLS/SSL Encryption

### Why TLS Matters

Without TLS:
- Email content transmitted in plaintext
- Anyone on the network can read emails
- Passwords and sensitive data exposed

With TLS:
- Email content encrypted
- Protection against eavesdropping
- Required for modern email standards

### Generating Certificates

#### Option 1: Self-Signed (Testing)
```bash
# Generate self-signed certificate
python scripts/generate_tls_cert.py

# Or manually
mkdir -p certs
cd certs
openssl req -x509 -newkey rsa:4096 -keyout server.key -out server.crt -days 365 -nodes
```

#### Option 2: Let's Encrypt (Production)
```bash
# Install certbot
sudo apt install certbot

# Generate certificate
sudo certbot certonly --standalone -d mail.yourdomain.com

# Set paths
export SMTP_TLS_CERT_PATH=/etc/letsencrypt/live/mail.yourdomain.com/fullchain.pem
export SMTP_TLS_KEY_PATH=/etc/letsencrypt/live/mail.yourdomain.com/privkey.pem
```

### TLS Ports

- **Port 465** - SMTPS (TLS from connection start)
- **Port 587** - SMTP with STARTTLS (upgrade to TLS)
- **Port 2525** - Non-standard, often used for testing

### Force TLS Mode

To reject non-TLS connections:
```bash
export SMTP_TLS_FORCE=true
```

**Warning:** This may break compatibility with old mail servers.

## Production Security Checklist

Before opening to the internet:

- [ ] Rate limiting enabled with appropriate limits
- [ ] SPF validation enabled
- [ ] Greylisting enabled (5-minute delay)
- [ ] TLS certificates installed (Let's Encrypt recommended)
- [ ] Firewall configured (only ports 25, 465, 587 open)
- [ ] Port forwarding configured on router
- [ ] DNS MX record points to your server
- [ ] Test receiving from Gmail/Outlook
- [ ] Monitor logs for first few days
- [ ] Set up log rotation (optional)

## Monitoring Security

### View Security Logs

```bash
# View all mail server logs
journalctl -u mail-server -f

# Filter for security events
journalctl -u mail-server | grep -E "(SPF|greylist|rate|blocked)"
```

### Check Greylist Stats

```python
from smtp_server.security import GreylistManager
greylist = GreylistManager()
print(greylist.get_stats())
```

### View Rate Limiter Stats

```python
from smtp_server.security import RateLimiter
rl = RateLimiter()
print(rl.get_stats('192.168.1.1'))  # Specific IP
```

## Troubleshooting

### Emails Being Rejected

**Check SPF:**
```bash
# Check if sender has SPF record
dig TXT senderdomain.com | grep spf
```

**Check Greylist:**
Look for "Greylisted" in logs. First email from new sender will be delayed.

**Check Rate Limits:**
Look for "Rate limit exceeded" in logs. May need to increase limits.

### TLS Connection Failures

**Verify certificates:**
```bash
openssl x509 -in /path/to/cert.pem -text -noout
```

**Check certificate expiry:**
```bash
openssl x509 -in /path/to/cert.pem -noout -dates
```

### Disabling All Security (Not Recommended)

For debugging only:
```bash
export SMTP_RATE_LIMIT_ENABLED=false
export SMTP_SPF_ENABLED=false
export SMTP_GREYLIST_ENABLED=false
export SMTP_TLS_ENABLED=false
python start_servers.py
```

## Security Best Practices

1. **Start conservative** - Use default settings, adjust based on needs
2. **Monitor logs** - Watch for patterns of blocked/accepted emails
3. **Keep certificates updated** - Set up auto-renewal for Let's Encrypt
4. **Regular backups** - Database contains greylist and rate limit data
5. **Firewall rules** - Only open necessary ports
6. **Stay updated** - Keep dependencies updated

## Support

For security issues or questions:
- Check logs first: `journalctl -u mail-server -n 100`
- Test configuration: `python -c "from smtp_server.security import security_config; print(security_config)"`
- Review this guide for feature explanations
