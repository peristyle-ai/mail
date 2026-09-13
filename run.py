from app import app

# WARNING: This file enables Flask debug mode (debug=True) which exposes the
# Werkzeug interactive debugger — it allows arbitrary code execution via the
# browser. NEVER use this file in production or on any network-accessible host.
# Use start_servers.py instead, which defaults to debug=False.

if __name__ == '__main__':
	app.run(debug=True)
