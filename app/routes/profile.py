from flask import Blueprint, request, jsonify, send_from_directory
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models.user import User
from bson.objectid import ObjectId
from datetime import datetime, timezone
import os
import uuid
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
API_BASE_URL = os.getenv("BASE_URL", "http://192.168.1.54:5000")  # Fallback to correct host
logger = logging.getLogger(__name__)
logger.debug(f"Base URL for Profile: {API_BASE_URL}")

# Validate API_BASE_URL
if not API_BASE_URL or not API_BASE_URL.startswith("http"):
    logger.error(f"Invalid BASE_URL: {API_BASE_URL}")
    raise ValueError("BASE_URL must be a valid URL starting with http:// or https://")

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s: %(message)s',
    handlers=[
        logging.FileHandler('flask.log'),
        logging.StreamHandler()
    ]
)

bp = Blueprint("profile", __name__, url_prefix="/user/api")

# Ensure upload directory exists
UPLOAD_FOLDER = "uploads/avatars"
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
    logger.info(f"Created directory: {UPLOAD_FOLDER}")

# Serve static files from uploads/avatars
@bp.route("/avatars/<path:filename>")
def serve_avatar(filename):
    logger.debug(f"Attempting to serve file: {UPLOAD_FOLDER}/{filename}")
    file_path = os.path.join(UPLOAD_FOLDER, filename)
    if not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        return jsonify({"error": f"File not found: {filename}"}), 404
    try:
        return send_from_directory(UPLOAD_FOLDER, filename)
    except Exception as e:
        logger.error(f"Error serving file {filename}: {str(e)}")
        return jsonify({"error": f"Failed to serve file: {filename}"}), 500

@bp.route("/profile", methods=["GET", "PUT"])
@jwt_required()
def user_profile():
    user_id = get_jwt_identity()
    logger.debug(f"Fetching profile for user_id: {user_id}")
    user = User.find_by_id(user_id)
    
    if not user:
        logger.error(f"User not found: {user_id}")
        return jsonify({"error": "User not found"}), 404

    if request.method == "GET":
        # Construct full avatar URL dynamically using /avatars
        avatar = user.get("avatar")
        full_avatar_url = f"{API_BASE_URL}{avatar}" if avatar else None
        logger.debug(f"Returning profile data: {user}, full avatar URL: {full_avatar_url}")
        return jsonify({
            "fullName": user.get("fullName"),
            "email": user.get("email"),
            "role": user.get("role"),
            "isActive": user.get("isActive"),
            "avatar": full_avatar_url
        }), 200
    
    if request.method == "PUT":
        update_data = {}
        logger.debug(f"Received PUT request: {request.content_type}")
        
        # Handle form data (for file uploads and fullName)
        if request.content_type.startswith("multipart/form-data"):
            # Handle fullName
            full_name = request.form.get("fullName")
            if full_name:
                if not isinstance(full_name, str) or len(full_name.strip()) < 2:
                    logger.error("Invalid fullName provided")
                    return jsonify({"error": "fullName must be a string with at least 2 characters"}), 400
                update_data["fullName"] = full_name

            # Handle avatar file
            if "avatar" in request.files:
                file = request.files["avatar"]
                if file and file.filename:
                    # Validate file type and size
                    allowed_extensions = {".jpg", ".jpeg", ".png"}
                    file_ext = os.path.splitext(file.filename)[1].lower()
                    if file_ext not in allowed_extensions:
                        logger.error(f"Invalid file extension: {file_ext}")
                        return jsonify({"error": "Avatar must be a JPG, JPEG, or PNG image"}), 400
                    if file.content_length and file.content_length > 5 * 1024 * 1024:
                        logger.error("File size exceeds 5MB limit")
                        return jsonify({"error": "File size exceeds 5MB limit"}), 400
                    
                    # Generate unique filename
                    filename = f"{uuid.uuid4().hex}{file_ext}"
                    file_path = os.path.join(UPLOAD_FOLDER, filename)
                    file.save(file_path)
                    logger.debug(f"Saved file to: {file_path}")
                    
                    # Store relative path in the database
                    relative_avatar_url = f"/avatars/{filename}"
                    logger.debug(f"Storing relative avatar URL: {relative_avatar_url}")
                    update_data["avatar"] = relative_avatar_url

        # Handle JSON data (for backward compatibility with URL-based updates)
        else:
            data = request.get_json(silent=True)
            if not data:
                logger.error("No data provided in PUT request")
                return jsonify({"error": "No data provided"}), 400

            # Validate and sanitize input
            allowed_fields = {"fullName", "avatar"}
            update_data = {k: v for k, v in data.items() if k in allowed_fields}
            
            if not update_data:
                logger.error("No valid fields provided for update")
                return jsonify({"error": "No valid fields provided for update"}), 400

            # Validate specific fields
            if "fullName" in update_data:
                if not isinstance(update_data["fullName"], str) or len(update_data["fullName"].strip()) < 2:
                    logger.error("Invalid fullName in JSON data")
                    return jsonify({"error": "fullName must be a string with at least 2 characters"}), 400

            if "avatar" in update_data:
                if not isinstance(update_data["avatar"], str) or not update_data["avatar"].startswith("/avatars/"):
                    logger.error("Invalid avatar URL in JSON data")
                    return jsonify({"error": "Avatar must be a valid relative URL starting with /avatars/"}), 400

        # Check if there is any data to update
        if not update_data:
            logger.error("No valid data provided for update")
            return jsonify({"error": "No valid data provided for update"}), 400

        # Add updatedAt timestamp
        update_data["updatedAt"] = datetime.now(timezone.utc)

        # Update user in database
        logger.debug(f"Updating user with data: {update_data}")
        updated_user = User.find_one_and_update(
            {"_id": ObjectId(user_id)},
            {"$set": update_data},
            return_document=True
        )

        if not updated_user:
            logger.error("Failed to update profile")
            return jsonify({"error": "Failed to update profile"}), 500

        # Construct full avatar URL for response
        avatar = updated_user.get("avatar")
        full_avatar_url = f"{API_BASE_URL}{avatar}" if avatar else None
        logger.debug(f"Profile updated successfully: {updated_user}, full avatar URL: {full_avatar_url}")
        return jsonify({
            "message": "Profile updated successfully",
            "user": {
                "fullName": updated_user.get("fullName"),
                "email": updated_user.get("email"),
                "role": updated_user.get("role"),
                "isActive": updated_user.get("isActive"),
                "avatar": full_avatar_url
            }
        }), 200