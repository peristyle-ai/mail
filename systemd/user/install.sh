#!/bin/bash
# Installation script for user-level mail-server systemd service

set -e

# Detect project root from script location
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

echo "Installing Mail Server systemd user service..."
echo "Project root: $PROJECT_ROOT"

if [ ! -f "$PROJECT_ROOT/.env" ]; then
    echo "Error: .env file not found at $PROJECT_ROOT/.env"
    exit 1
fi

# Create systemd user directory if it doesn't exist
mkdir -p ~/.config/systemd/user

# Copy service file with project path filled in
sed "s|__PROJECT_ROOT__|$PROJECT_ROOT|g" "$PROJECT_ROOT/systemd/user/mail-server.service" > ~/.config/systemd/user/mail-server.service

# Make scripts executable
chmod +x "$PROJECT_ROOT/start_mail_server.sh"
chmod +x "$PROJECT_ROOT/start_servers.py"

# Create uploads directory if it doesn't exist
mkdir -p "$PROJECT_ROOT/uploads"

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
