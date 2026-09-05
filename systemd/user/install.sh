#!/bin/bash
# Installation script for user-level mail-server systemd services
#
# Installs:
#   * mail-server.service          (Flask + SMTP, unchanged)
#   * mail-server-embeddings.service (PR1: embedding worker)
#
# Both run as your user — no sudo needed for service start/stop.

set -e

# Detect project root from script location
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

echo "Installing Mail Server systemd user services..."
echo "Project root: $PROJECT_ROOT"

if [ ! -f "$PROJECT_ROOT/.env" ]; then
    echo "Error: .env file not found at $PROJECT_ROOT/.env"
    exit 1
fi

# Create systemd user directory if it doesn't exist
mkdir -p ~/.config/systemd/user

# Copy both service files with project path filled in
for svc in mail-server.service mail-server-embeddings.service; do
    SRC="$PROJECT_ROOT/systemd/user/$svc"
    if [ -f "$SRC" ]; then
        sed "s|__PROJECT_ROOT__|$PROJECT_ROOT|g" "$SRC" > ~/.config/systemd/user/$svc
        echo "Installed $svc"
    else
        echo "Skipped $svc (not present)"
    fi
done

# Make scripts executable
chmod +x "$PROJECT_ROOT/start_mail_server.sh"
chmod +x "$PROJECT_ROOT/start_servers.py"
chmod +x "$PROJECT_ROOT/scripts/run_embedding_worker.py"

# Create uploads directory if it doesn't exist
mkdir -p "$PROJECT_ROOT/uploads"

# Reload systemd user daemon
echo "Reloading systemd user daemon..."
systemctl --user daemon-reload

# Enable both services to start on user login
echo "Enabling mail-server user service..."
systemctl --user enable mail-server.service
echo "Enabling mail-server-embeddings user service..."
systemctl --user enable mail-server-embeddings.service

echo ""
echo "Installation complete!"
echo ""
echo "User Service Commands (no sudo needed):"
echo "  systemctl --user start mail-server                  # Start mail server"
echo "  systemctl --user start mail-server-embeddings       # Start embedding worker"
echo "  systemctl --user stop  mail-server                  # Stop"
echo "  systemctl --user restart mail-server-embeddings     # Restart embedding worker"
echo "  systemctl --user status mail-server                 # Status"
echo "  journalctl --user -u mail-server -f                 # Mail-server logs"
echo "  journalctl --user -u mail-server-embeddings -f      # Embedding worker logs"
echo ""
echo "To start on boot (optional):"
echo "  sudo loginctl enable-linger \$USER"
echo ""
echo "The services will automatically start when you log in."
echo ""
echo "PR1 first-run checklist:"
echo "  1. psql \$DATABASE_URL -f db/migrations/003_email_chunks_and_embedding_jobs.sql"
echo "  2. systemctl --user restart mail-server  (so hooks fire on new mail)"
echo "  3. systemctl --user start  mail-server-embeddings"
echo "  4. python scripts/backfill_embeddings.py --status"
echo "  5. python scripts/backfill_embeddings.py --dry-run --limit 10"
echo "  6. python scripts/backfill_embeddings.py              # full backfill"
