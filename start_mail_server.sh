#!/bin/bash
# Start script for mail server - runs both Flask API and SMTP server

# Change to project directory
cd /opt/py_pg_accounts/git/py_pg_email

# Activate virtual environment
source venv/bin/activate

# Set environment variables
export FLASK_APP=run.py
export FLASK_ENV=production
export PYTHONPATH=/opt/py_pg_accounts/git/py_pg_email

# Create logs directory if it doesn't exist
mkdir -p /opt/py_pg_accounts/git/py_pg_email/logs

# Start both servers using the combined startup script
exec python start_servers.py --flask-port 5000 --smtp-port 2525
