#!/bin/bash
# Start script for mail server - runs both Flask API and SMTP server

# Detect project root from script location
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"

# Change to project directory
cd "$PROJECT_ROOT"

# Activate virtual environment
source venv/bin/activate

# Set environment variables
export FLASK_APP=run.py
export FLASK_ENV=production
export PYTHONPATH="$PROJECT_ROOT"

# Create logs directory if it doesn't exist
mkdir -p "$PROJECT_ROOT/logs"

# Start both servers using the combined startup script
exec python start_servers.py --flask-port 5003 --smtp-port 2525
