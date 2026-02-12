# User-Level Systemd Service

This directory contains user-level systemd service files for the mail server.
User-level services don't require sudo/root privileges and run under your user account.

## Installation (No sudo required!)

```bash
bash ~/git/py_pg_email/systemd/user/install.sh
```

Or manually:

```bash
# Create user systemd directory
mkdir -p ~/.config/systemd/user

# Copy service file
cp ~/git/py_pg_email/systemd/user/mail-server.service ~/.config/systemd/user/

# Reload daemon
systemctl --user daemon-reload

# Enable service (starts on login)
systemctl --user enable mail-server

# Start now
systemctl --user start mail-server
```

## User Commands (No sudo!)

```bash
# Start/Stop/Restart
systemctl --user start mail-server
systemctl --user stop mail-server
systemctl --user restart mail-server

# Check status
systemctl --user status mail-server

# View logs
journalctl --user -u mail-server -f
journalctl --user -u mail-server --since today

# Enable/disable auto-start
systemctl --user enable mail-server   # Start on login
systemctl --user disable mail-server  # Don't start on login
```

## Start on Boot (Even without login)

To make the service start at system boot (not just when you log in):

```bash
# Enable "linger" for your user (requires sudo once)
sudo loginctl enable-linger $USER

# Then enable the service
systemctl --user enable mail-server
```

Now the mail server will start automatically when the system boots, even if you're not logged in.

## Differences from System Service

| Feature | User Service | System Service |
|---------|--------------|----------------|
| sudo required | ❌ No | ✅ Yes |
| Logs location | `journalctl --user` | `sudo journalctl -u` |
| Starts on login | ✅ Yes | ✅ On boot |
| Can start on boot | ✅ With linger | ✅ Default |
| Multi-user | ❌ Only your user | ✅ All users |

## Troubleshooting

**Service won't start:**
```bash
# Check what's wrong
systemctl --user status mail-server

# Check logs
journalctl --user -u mail-server -n 50
```

**Port already in use:**
```bash
# Kill existing processes
pkill -f start_servers
systemctl --user restart mail-server
```

**Environment variables not set:**
Edit `~/.config/systemd/user/mail-server.service` and add:
```
Environment=YOUR_VAR=value
```

Then reload:
```bash
systemctl --user daemon-reload
systemctl --user restart mail-server
```
