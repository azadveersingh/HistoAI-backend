from flask import Blueprint, request, jsonify, render_template
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from google.oauth2 import id_token
from google.auth.transport.requests import Request
from ..models.user import User, UserRoles
from ..helpers.validation_helpers import is_valid_email
from ..extensions import bcrypt, mongo  
from bson.objectid import ObjectId
import traceback
import logging
import random
import smtplib
from datetime import datetime, timezone


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bp = Blueprint("auth", __name__, url_prefix="/api")

@bp.route("/hello", methods=["GET"])
def index():
    return jsonify({"message": "Hello, World!"})

@bp.route("/register", methods=["POST"])
def register():
    data = request.get_json()
    name = data.get("name")
    email = data.get("email")
    password = data.get("password")

    if not all([name, email, password]):
        return jsonify({"message": "All fields are required"}), 400
    if len(password) < 8:
        return jsonify({"message": "Password must be at least 8 characters long"}), 400

    if User.find_by_email(email):
        return jsonify({"message": "User already exists"}), 400

    user_id = User.create(name, email, password)
    logger.info(f"User registered: {email}, ID: {user_id}")
    return jsonify({"message": "User registered successfully", "user_id": str(user_id)}), 201

@bp.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"message": "Email and password are required"}), 400

    user = User.find_by_email(email)
    if not user or not bcrypt.check_password_hash(user["password"], password):
        return jsonify({"message": "Invalid credentials"}), 401

    # Allow login if user is active or is an admin
    if user.get("role") != UserRoles.ADMIN and not user.get("isActive", False):
        return jsonify({"message": "Your account is deactivated. Please contact an admin."}), 403

    
    if not user.get("isVerified"):
        return jsonify({"message": "Please verify your email first."}), 403

    if user.get("isBlocked"):
        return jsonify({"message": "Account is blocked by admin."}), 403

    if user.get("isLocked"):
        return jsonify({"message": "Account is locked due to multiple failed attempts."}), 403

    access_token = create_access_token(identity=str(user["_id"]))
    logger.info(f"User logged in: {email}, Token: {access_token}")
    return jsonify({
        "access_token": access_token,
        "message": "Logged in successfully",
        "role": user.get("role", 0),
        "isActive": user.get("isActive", 1),  # Include isActive for frontend
        "user": {
            "_id": str(user["_id"]),
            "name": user.get("name"),
            "email": user.get("email"),
            "avatar": user.get("avatar")
        }
    }), 200

@bp.route("/users/<user_id>", methods=["PATCH"])
@jwt_required()
def update_user_status(user_id):
    try:
        if not ObjectId.is_valid(user_id):
            return jsonify({"message": "Invalid user ID"}), 400

        data = request.get_json()
        if not data or "isActive" not in data:
            return jsonify({"message": "Missing 'isActive' in request body"}), 400

        is_active = data.get("isActive")
        if is_active not in [0, 1]:
            return jsonify({"message": "isActive must be 0 (inactive) or 1 (active)"}), 400

        user = User.find_by_id(user_id)
        if not user:
            return jsonify({"message": "User not found"}), 404

        if user.get("role") == UserRoles.ADMIN and not is_active:
            return jsonify({"message": "Admins cannot be deactivated"}), 403


        # Update and verify directly with MongoDB
        mongo.db.users.update_one({"_id": ObjectId(user_id)}, {"$set": {"isActive": is_active, "lastLogin":datetime.now(timezone.utc), "loginAttempts":0}})
        updated_user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
        
        if not updated_user:
            return jsonify({"message": "User not found after update"}), 404

        updated_user["_id"] = str(updated_user["_id"])
        logger.info(f"User status updated: {user['email']} to isActive={is_active}, Updated document: {updated_user}")
        return jsonify({
            "message": "User status updated successfully",
            "user": {
                "_id": updated_user["_id"],
                "name": updated_user.get("name"),
                "email": updated_user.get("email"),
                "role": updated_user.get("role", 0),
                "isActive": updated_user.get("isActive", 0)
            }
        }), 200

    except Exception as e:
        logger.error(f"Error updating user status: {str(e)}")
        traceback.print_exc()
        return jsonify({"message": "Server error", "error": str(e)}), 500

@bp.route("/users", methods=["GET"])
@jwt_required()
def get_all_users():
    try:
        users = User.get_all_users()
        logger.info(f"Fetched all users: {users}")
        return jsonify(users), 200
    except Exception as e:
        logger.error(f"Error fetching users: {str(e)}")
        traceback.print_exc()
        return jsonify({"message": "Server error", "error": str(e)}), 500

@bp.route("/uploads", methods=["GET"])
@jwt_required()
def get_all_uploads():
    try:
        uploads = mongo.db.uploads.find()
        uploads_list = [
            {
                "_id": str(upload["_id"]),
                "filename": upload.get("filename"),
                "file_url": upload.get("file_url"),
                "user_id": str(upload.get("user_id")),
                "upload_time": upload.get("upload_time")
            }
            for upload in uploads
        ]
        logger.info(f"Returning uploads from /api/uploads: {uploads_list}")
        return jsonify(uploads_list), 200
    except Exception as e:
        logger.error(f"Error fetching uploads: {str(e)}")
        traceback.print_exc()
        return jsonify({"message": "Server error", "error": str(e)}), 500

@bp.route("/protected", methods=["GET"])
@jwt_required()
def protected():
    user_id = get_jwt_identity()
    user = User.find_by_id(user_id)
    if not user:
        return jsonify({"message": "User not found"}), 404
    return jsonify({"message": "Access granted", "user": {"email": user["email"]}}), 200

@bp.route("/checkLogged", methods=["GET"])
@jwt_required()
def check_logged():
    user_id = get_jwt_identity()
    user = User.find_by_id(user_id)
    if not user:
        return jsonify({"status": 401, "message": "Not Logged"}), 401
    return jsonify({
        "status": 200,
        "message": "Logged In",
        "user": {
            "email": user["email"],
            "name": user.get("name"),
            "avatar": user.get("avatar")
        }
    }), 200

@bp.route("/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh():
    identity = get_jwt_identity()
    new_access_token = create_access_token(identity=identity)
    return jsonify({"access_token": new_access_token})

@bp.route("/google-login", methods=["POST"])
def google_login():
    try:
        data = request.get_json()
        id_token_str = data.get("token")
        if not id_token_str:
            return jsonify({"message": "Missing token"}), 400

        try:
            credentials = id_token.verify_oauth2_token(
                id_token_str,
                Request(),
                "364205782321-tcdg1lfsn9psg8c6qft9pv1mlp9tv2j9.apps.googleusercontent.com"
            )
        except ValueError as e:
            return jsonify({"message": "Invalid token", "error": str(e)}), 401

        email = credentials.get("email")
        user = User.find_by_email(email)

        if not user:
            user_data = {
                "name": credentials.get("name", "Unknown User"),
                "email": email,
                "password": None,
                "bio": "",
                "status": "Available",
                "avatar": credentials.get("picture"),
                "role": UserRoles.USER,
                "isActive": 1  # Set to active by default
            }
            user_id = User.create(**user_data)
            user = User.find_by_id(user_id)

        if user.get("role", 0) != 1 and user.get("isActive", 1) == 0:
            return jsonify({"message": "Your account is deactivated. Please contact an admin."}), 403

        access_token = create_access_token(identity=str(user["_id"]))
        logger.info(f"Google login: {email}, Token: {access_token}")
        return jsonify({
            "access_token": access_token,
            "message": "Logged in successfully",
            "userProfile": {
                "name": user.get("name"),
                "email": user.get("email"),
                "avatar": user.get("avatar"),
                "role": user.get("role", 0),
                "isActive": user.get("isActive", 1)
            }
        }), 200

    except Exception as e:
        logger.error(f"Google login failed: {str(e)}")
        traceback.print_exc()
        return jsonify({"message": "Google login failed", "error": str(e)}), 500