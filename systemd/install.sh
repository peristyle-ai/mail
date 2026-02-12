#!/bin/bash
# Installation script for mail-server systemd service (system-level)
# This installs to /etc/systemd/system/ (requires sudo)

set -e

echo "Installing Mail Server systemd service (system-level)..."
echo "This will install to: /etc/systemd/system/"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root (use sudo)"
    exit 1
fi

# Read JWT_SECRET from .env file
if [ -f /opt/py_pg_accounts/git/py_pg_email/.env ]; then
    JWT_SECRET=$(grep '^JWT_SECRET=' /opt/py_pg_accounts/git/py_pg_email/.env | cut -d '=' -f2)
    if [ -z "$JWT_SECRET" ]; then
        echo "Error: JWT_SECRET not found in .env file"
        exit 1
    fi
    echo "Using JWT_SECRET from .env file"
else
    echo "Error: .env file not found at /opt/py_pg_accounts/git/py_pg_email/.env"
    exit 1
fi

# Update service file with JWT_SECRET
sed -i "s/JWT_SECRET=.*/JWT_SECRET=${JWT_SECRET}/" /opt/py_pg_accounts/git/py_pg_email/systemd/mail-server.service

# Copy service file
cp /opt/py_pg_accounts/git/py_pg_email/systemd/mail-server.service /etc/systemd/system/

# Make scripts executable
chmod +x /opt/py_pg_accounts/git/py_pg_email/start_mail_server.sh
chmod +x /opt/py_pg_accounts/git/py_pg_email/start_servers.py

# Create uploads directory with proper permissions
mkdir -p /opt/py_pg_accounts/git/py_pg_email/uploads
chown -R mal:mal /opt/py_pg_accounts/git/py_pg_email/uploads

# Reload systemd
echo "Reloading systemd..."
systemctl daemon-reload

# Enable service to start on boot
echo "Enabling mail-server service..."
systemctl enable mail-server.service

echo ""
echo "✓ Installation complete!"
echo ""
echo "System Commands (requires sudo):"
echo "  sudo systemctl start mail-server      # Start the service"
echo "  sudo systemctl stop mail-server       # Stop the service"
echo "  sudo systemctl restart mail-server    # Restart the service"
echo "  sudo systemctl status mail-server     # Check status"
echo "  sudo journalctl -u mail-server -f     # View logs"
echo ""
echo "The service will automatically start on system boot."
echo ""
echo "For user-level service (no sudo required), use:"
echo "  bash ~/git/py_pg_email/systemd/user/install.sh"
