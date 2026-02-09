from flask import Flask
from app.routes import bp as routes_bp
from app.routes.auth import bp as auth_bp

def create_app():
    app = Flask(__name__)
    app.register_blueprint(routes_bp)
    app.register_blueprint(auth_bp)
    return app

app = create_app()
