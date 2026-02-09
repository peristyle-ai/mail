from flask import Flask
from app.routes import bp as routes_bp
from app.routes.auth import bp as auth_bp
from app.routes.emails import bp as emails_bp
from app.routes.folders import bp as folders_bp
from app.routes.search import bp as search_bp

def create_app():
    app = Flask(__name__)
    app.register_blueprint(routes_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(emails_bp)
    app.register_blueprint(folders_bp)
    app.register_blueprint(search_bp)
    return app

app = create_app()
