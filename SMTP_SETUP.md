# Mail Server Setup with SMTP Support

## Quick Start

### 1. Start Both Servers

```bash
cd /opt/py_pg_accounts/git/py_pg_email
source venv/bin/activate
python start_servers.py
```

This will start:
- **SMTP Server** on port 2525 (receives emails)
- **Flask API** on port 5001 (REST API + Swagger UI)

**Note:** If testing from another computer on your network, ensure the firewall allows port 2525:
```bash
sudo ufw allow 2525/tcp
```

### 2. Test from Same Computer

Open a new terminal:

```bash
cd /opt/py_pg_accounts/git/py_pg_email
source venv/bin/activate
python scripts/send_test_email.py --server 127.0.0.1 --to the operator@example.com.au
```

### 3. Test from Another Computer on Local Network

On another computer (192.168.4.x):

```bash
python scripts/send_test_email.py --server 192.168.4.30 --to the operator@example.com.au
```

Then check in pgAdmin or API:
```
http://192.168.4.30:5001/docs
```

### 4. Check Received Emails

**Via pgAdmin:**
- Connect to your PostgreSQL database
- Query the `emails` table

**Via API (requires authentication first):**
1. Register a user at `/auth/register`
2. Login at `/auth/login` to get JWT token
3. Click "Authorize" in Swagger and enter: `Bearer YOUR_TOKEN`
4. Call `GET /api/emails` to see received emails

---

## Internet Access (Advanced)

To receive emails from the internet:

### 1. Port Forwarding

On your router, forward:
- External port 2525 → Internal 192.168.4.30:2525

### 2. Firewall

Allow incoming TCP on port 2525:
```bash
# Ubuntu/Debian with ufw
sudo ufw allow 2525/tcp

# Or iptables
sudo iptables -A INPUT -p tcp --dport 2525 -j ACCEPT
```

### 3. DNS (For production)

Add MX record for your domain:
```
example.com.au.  IN  MX  10  your-public-ip-address.
```

### 4. Test from Gmail/External

Send an email to `the operator@example.com.au` from Gmail.
It should arrive in your database!

---

## Architecture

```
Internet / Gmail
      |
      | SMTP (Port 587)
      v
+-------------------+
|   SMTP Server     |  aiosmtpd
|   (Port 587)      |
+-------------------+
      |
      | Parse & Store
      v
+-------------------+
|   PostgreSQL      |
|   Database        |
+-------------------+
      |
      | REST API
      v
+-------------------+
|   Flask API       |  Port 5001
|   /api/emails     |
|   /docs (Swagger) |
+-------------------+
      |
      | Browser
      v
   User Interface
```

---

## File Structure

```
/opt/py_pg_accounts/git/py_pg_email/
├── smtp_server/          # NEW: SMTP server module
│   ├── __init__.py
│   ├── handler.py       # SMTP message handler
│   ├── server.py        # Server startup
│   └── email_storage.py # Database storage
├── scripts/             # NEW: Test scripts
│   └── send_test_email.py
├── start_servers.py     # NEW: Combined startup
├── SMTP_SETUP.md        # This file
├── app/                 # Existing Flask app
├── db/                  # Database schema
└── tests/               # Test suite
```

---

## Troubleshooting

### SMTP Server Won't Start

**Port already in use:**
```bash
# Find process using port 2525
sudo lsof -i :587
# Kill it
sudo kill -9 <PID>
```

**Permission denied (port < 1024):**
- Use port 2525 (recommended) or run with sudo for port 25

### Can't Send from Another Computer

1. **Check firewall:**
   ```bash
   sudo ufw status
   sudo ufw allow 2525/tcp
   ```

2. **Test connectivity:**
   ```bash
   # From other computer
   telnet 192.168.4.30 2525
   ```

3. **Check SMTP logs:**
   - SMTP server prints debug info to console

### Emails Not Appearing in Database

1. Check SMTP server console for errors
2. Verify PostgreSQL connection
3. Check that the recipient user exists or will be auto-created
4. Look at `email_recipients` table for routing info

---

## Security Notes

⚠️ **Important for Internet Exposure:**

1. **Rate Limiting** - Add rate limiting to prevent spam
2. **SPF Records** - Add DNS SPF record for your domain
3. **TLS/SSL** - Use SMTPS (port 465) with SSL certificates
4. **Authentication** - Currently accepts all incoming emails (standard for SMTP)
5. **Spam Filtering** - Consider integrating spam detection

For production use, consider:
- Running behind a reverse proxy (nginx)
- Using SSL certificates (Let's Encrypt)
- Implementing IP allowlists
- Adding SPF/DKIM validation

---

## API Endpoints

After starting servers, visit:
- **Swagger UI:** http://localhost:5001/docs
- **API Spec:** http://localhost:5001/api/spec.json

Key endpoints:
- `POST /auth/register` - Create user
- `POST /auth/login` - Get JWT token
- `GET /api/emails` - List emails (requires auth)
- `POST /api/emails` - Create email
- `GET /api/search` - Search emails

---

## Next Steps

1. ✅ Test locally from same machine
2. ✅ Test from other computer on network
3. ⬜ Configure port forwarding for internet access
4. ⬜ Set up DNS MX records (if using custom domain)
5. ⬜ Add TLS/SSL encryption
6. ⬜ Implement rate limiting
7. ⬜ Set up monitoring/logging
