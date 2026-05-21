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
from app.routes.inbound import inbound_bp

def create_app():
	app = Flask(__name__)
	
	# Enable CORS for all domains (safe for local development)
	CORS(app)
	
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
	app.register_blueprint(inbound_bp)
	return app

app = create_app()
