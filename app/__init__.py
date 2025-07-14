from flask import Flask, render_template
from flask_cors import CORS
from .config import Config
from .extensions import mongo, bcrypt, jwt, socketio

from .routes import auth, profile, file_upload, data, token_usage, file_routes,file_upload, otp_auth, project_routes, admin_routes


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
    CORS(app, resources={r"/*": {"origins": "*", "supports_credentials": True}})
 

    mongo.init_app(app)
    bcrypt.init_app(app)
    jwt.init_app(app)
    socketio.init_app(app, cors_allowed_origins="*")
  
    
    with app.app_context():
        print("MongoDB Instance:", mongo.db)
        
    from app import socket_events
        
    @app.route("/")
    def index():
        return render_template("index.html")
    
    # Register blueprints
    app.register_blueprint(auth.bp)
    app.register_blueprint(profile.bp)
    app.register_blueprint(file_upload.bp)
    app.register_blueprint(data.bp)
    app.register_blueprint(file_routes.bp)
    app.register_blueprint(token_usage.bp)
    app.register_blueprint(otp_auth.otp_bp)
    app.register_blueprint(project_routes.project_bp)
    app.register_blueprint(admin_routes.admin_bp)


    return app