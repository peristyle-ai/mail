from flask import Flask
from flasgger import Swagger
from flask_cors import CORS
from app.main_routes import bp as routes_bp
from app.routes.auth import bp as auth_bp
from app.routes.emails import bp as emails_bp
from app.routes.folders import bp as folders_bp
from app.routes.search import bp as search_bp
from app.routes.attachments import bp as attachments_bp
from app.routes.blacklist import bp as blacklist_bp
from app.routes.domains import bp as domains_bp
from app.routes.inbound import inbound_bp
from app.db import ensure_attachments_schema, ensure_domains_table, ensure_email_copy_schema, seed_local_domains

def create_app():
	app = Flask(__name__)
	# Schema-init helpers need DDL privileges (postgres role).
	# The runtime role `mail_external` doesn't have those, so we tolerate
	# permission errors here. For a fresh DB, run bin/setup_db.py once
	# as the postgres role to initialize the schema.
	for fn in (ensure_attachments_schema, ensure_email_copy_schema,
	           ensure_domains_table, seed_local_domains):
		try:
			fn()
		except Exception as e:
			app.logger.warning(
				f"schema init step {fn.__name__} skipped: {type(e).__name__}: {e}"
			)

	app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max upload
	app.config['MAX_FORM_MEMORY_SIZE'] = 50 * 1024 * 1024  # 50MB max form field size
	app.request_class.max_form_memory_size = 50 * 1024 * 1024  # 50MB per Werkzeug
	
	# CORS: restrict to known client origin(s). Set CORS_ORIGINS in .env as a
	# comma-separated list of allowed origins (e.g. your public domain via tunnel,
	# plus localhost for dev). If unset, defaults to localhost-only (most restrictive).
	import os as _os
	_cors_origins = [o.strip() for o in _os.getenv('CORS_ORIGINS', '').split(',') if o.strip()]
	if not _cors_origins:
		_cors_origins = ['http://127.0.0.1:5005', 'http://localhost:5005']
	app.logger.info(f"CORS origins: {_cors_origins}")
	CORS(app, origins=_cors_origins, supports_credentials=True)
	
	# Swagger configuration
	swagger_config = {
		'headers': [],
		'specs': [
			{
				'endpoint': 'apispec',
				'route': '/api/spec.json',
				'rule_filter': lambda rule: True,
				'model_filter': lambda tag: True,
			}
		],
		'static_url_path': '/flasgger_static',
		'swagger_ui': True,
		'specs_route': '/docs',
		'title': 'Mail Server API',
		'version': '1.0.0',
		'description': 'REST API for local email management with JWT authentication',
		'uiversion': 3,
		'securityDefinitions': {
			'Bearer': {
				'type': 'apiKey',
				'name': 'Authorization',
				'in': 'header',
				'description': 'JWT Token. Example: "Bearer {token}"'
			}
		}
	}
	
	Swagger(app, config=swagger_config)
	
	app.register_blueprint(routes_bp)
	app.register_blueprint(auth_bp)
	app.register_blueprint(emails_bp)
	app.register_blueprint(folders_bp)
	app.register_blueprint(search_bp)
	app.register_blueprint(attachments_bp)
	app.register_blueprint(blacklist_bp)
	app.register_blueprint(domains_bp)
	app.register_blueprint(inbound_bp)
	return app

app = create_app()
