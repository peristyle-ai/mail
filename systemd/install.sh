#!/bin/bash
# Installation script for mail-server systemd service (system-level)
# This installs to /etc/systemd/system/ (requires sudo)

set -e

# Allow PROJECT_ROOT to be set as environment variable, otherwise detect from script location
if [ -z "$PROJECT_ROOT" ]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
fi

echo "Installing Mail Server systemd service (system-level)..."
echo "This will install to: /etc/systemd/system/"
echo "Project root: $PROJECT_ROOT"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root (use sudo)"
    exit 1
fi

if [ ! -f "$PROJECT_ROOT/.env" ]; then
    echo "Error: .env file not found at $PROJECT_ROOT/.env"
    exit 1
fi

# Copy service file with project path filled in
sed "s|__PROJECT_ROOT__|$PROJECT_ROOT|g" "$PROJECT_ROOT/systemd/mail-server.service" > /etc/systemd/system/mail-server.service

# Make scripts executable
chmod +x "$PROJECT_ROOT/start_mail_server.sh"
chmod +x "$PROJECT_ROOT/start_servers.py"

# Create uploads directory with proper permissions
mkdir -p "$PROJECT_ROOT/uploads"

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
