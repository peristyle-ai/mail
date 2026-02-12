#!/bin/bash
# Installation script for user-level mail-server systemd service

set -e

echo "Installing Mail Server systemd user service..."

# Read JWT_SECRET from .env file
if [ -f ~/git/py_pg_email/.env ]; then
    JWT_SECRET=$(grep '^JWT_SECRET=' ~/git/py_pg_email/.env | cut -d '=' -f2)
    if [ -z "$JWT_SECRET" ]; then
        echo "Error: JWT_SECRET not found in .env file"
        exit 1
    fi
    echo "Using JWT_SECRET from .env file"
else
    echo "Error: .env file not found at ~/git/py_pg_email/.env"
    exit 1
fi

# Update service file with JWT_SECRET
sed -i "s/JWT_SECRET=.*/JWT_SECRET=${JWT_SECRET}/" ~/git/py_pg_email/systemd/user/mail-server.service

# Create systemd user directory if it doesn't exist
mkdir -p ~/.config/systemd/user

# Copy service file
cp /opt/py_pg_accounts/git/py_pg_email/systemd/user/mail-server.service ~/.config/systemd/user/

# Make scripts executable
chmod +x /opt/py_pg_accounts/git/py_pg_email/start_mail_server.sh
chmod +x /opt/py_pg_accounts/git/py_pg_email/start_servers.py

# Create uploads directory if it doesn't exist
mkdir -p /opt/py_pg_accounts/git/py_pg_email/uploads

# Reload systemd user daemon
echo "Reloading systemd user daemon..."
systemctl --user daemon-reload

# Enable service to start on user login
echo "Enabling mail-server user service..."
systemctl --user enable mail-server.service

echo ""
echo "Installation complete!"
echo ""
echo "User Service Commands (no sudo needed):"
echo "  systemctl --user start mail-server      # Start the service"
echo "  systemctl --user stop mail-server       # Stop the service"
echo "  systemctl --user restart mail-server     # Restart the service"
echo "  systemctl --user status mail-server      # Check status"
echo "  journalctl --user -u mail-server -f     # View logs"
echo ""
echo "To start on boot (optional):"
echo "  sudo loginctl enable-linger \$USER"
echo ""
echo "The service will automatically start when you log in."
