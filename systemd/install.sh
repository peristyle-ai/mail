#!/bin/bash
# Installation script for user-level mail-server systemd service
# This installs to ~/.config/systemd/user/ (no sudo required!)

set -e

echo "Installing Mail Server systemd user service..."
echo "Installing to: ~/.config/systemd/user/"
echo ""

# Create user systemd directory if it doesn't exist
mkdir -p ~/.config/systemd/user

# Copy service file from user directory
cp ~/git/py_pg_email/systemd/user/mail-server.service ~/.config/systemd/user/

# Make scripts executable
chmod +x ~/git/py_pg_email/start_mail_server.sh
chmod +x ~/git/py_pg_email/start_servers.py

# Create uploads directory if it doesn't exist
mkdir -p ~/git/py_pg_email/uploads

# Reload systemd user daemon
echo "Reloading systemd user daemon..."
systemctl --user daemon-reload

# Enable service to start on user login
echo "Enabling mail-server user service..."
systemctl --user enable mail-server.service

echo ""
echo "✓ Installation complete!"
echo ""
echo "User Commands (no sudo needed):"
echo "  systemctl --user start mail-server      # Start the service"
echo "  systemctl --user stop mail-server       # Stop the service"  
echo "  systemctl --user restart mail-server    # Restart the service"
echo "  systemctl --user status mail-server     # Check status"
echo "  journalctl --user -u mail-server -f     # View logs"
echo ""
echo "Optional - Start on system boot:"
echo "  sudo loginctl enable-linger \$USER"
echo ""
echo "The service will automatically start when you log in."
