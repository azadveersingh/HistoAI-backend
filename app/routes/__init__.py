from flask import Blueprint

def register_blueprints(app):
    from .auth import auth
    from .google_login_routes import google_login_bp
    from .profile import profile
    from .file_routes import file_bp
    from .data_routes import data_bp
    from .data import excel_bp
    from .token_usage import token_usage
    from .data import excel_data 
    from .otp_auth import otp_bp
    from .project_routes import project_bp
    from .admin_routes import admin_bp
    from .book_routes import book_bp
    from .collection_routes import collection_bp
    

  



    app.register_blueprint(auth)
    app.register_blueprint(profile)
    app.register_blueprint(file_bp)
    app.register_blueprint(google_login_bp)
    app.register_blueprint(excel_data)
    app.register_blueprint(token_usage)
    app.register_blueprint(otp_bp)
    app.register_blueprint(project_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(book_bp)
    app.register_blueprint(collection_bp)

