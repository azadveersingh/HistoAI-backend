
from flask import Blueprint, request, jsonify, send_from_directory
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models.user import User
from ..config import Config
from bson.objectid import ObjectId
from datetime import datetime, timezone
import os
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
logger = logging.getLogger(__name__)

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
        avatar = user.get("avatar")
        logger.debug(f"Returning profile data: {user}, avatar: {avatar}")
        return jsonify({
            "fullName": user.get("fullName"),
            "email": user.get("email"),
            "role": user.get("role"),
            "isActive": user.get("isActive"),
            "avatar": avatar  # Return relative path
        }), 200
    
    if request.method == "PUT":
        update_data = {}
        logger.debug(f"Received PUT request: {request.content_type}")
        
        if request.content_type.startswith("multipart/form-data"):
            full_name = request.form.get("fullName")
            if full_name:
                if not isinstance(full_name, str) or len(full_name.strip()) < 2:
                    logger.error("Invalid fullName provided")
                    return jsonify({"error": "fullName must be a string with at least 2 characters"}), 400
                update_data["fullName"] = full_name

            if "avatar" in request.files:
                file = request.files["avatar"]
                if file and file.filename:
                    allowed_extensions = {".jpg", ".jpeg", ".png"}
                    file_ext = os.path.splitext(file.filename)[1].lower()
                    if file_ext not in allowed_extensions:
                        logger.error(f"Invalid file extension: {file_ext}")
                        return jsonify({"error": "Avatar must be a JPG, JPEG, or PNG image"}), 400
                    if file.content_length and file.content_length > 5 * 1024 * 1024:
                        logger.error("File size exceeds 5MB limit")
                        return jsonify({"error": "File size exceeds 5MB limit"}), 400
                    
                    # Create user-specific avatar folder
                    user_avatar_dir = os.path.join(Config.AVATAR_UPLOAD_DIR, user_id)
                    os.makedirs(user_avatar_dir, exist_ok=True)
                    filename = "img.jpg"
                    file_path = os.path.join(user_avatar_dir, filename)
                    file.save(file_path)
                    logger.debug(f"Saved avatar to: {file_path}")
                    
                    relative_avatar_url = f"{user_id}/img.jpg"
                    logger.debug(f"Storing relative avatar URL: {relative_avatar_url}")
                    update_data["avatar"] = relative_avatar_url

        else:
            data = request.get_json(silent=True)
            if not data:
                logger.error("No data provided in PUT request")
                return jsonify({"error": "No data provided"}), 400

            allowed_fields = {"fullName", "avatar"}
            update_data = {k: v for k, v in data.items() if k in allowed_fields}
            
            if not update_data:
                logger.error("No valid fields provided for update")
                return jsonify({"error": "No valid fields provided for update"}), 400

            if "fullName" in update_data:
                if not isinstance(update_data["fullName"], str) or len(update_data["fullName"].strip()) < 2:
                    logger.error("Invalid fullName in JSON data")
                    return jsonify({"error": "fullName must be a string with at least 2 characters"}), 400

            if "avatar" in update_data:
                if not isinstance(update_data["avatar"], str) or not update_data["avatar"].startswith(f"{user_id}/"):
                    logger.error("Invalid avatar URL in JSON data")
                    return jsonify({"error": f"Avatar must be a valid relative URL starting with {user_id}/"}), 400

        if not update_data:
            logger.error("No valid data provided for update")
            return jsonify({"error": "No valid data provided for update"}), 400

        update_data["updatedAt"] = datetime.now(timezone.utc)

        logger.debug(f"Updating user with data: {update_data}")
        updated_user = User.find_one_and_update(
            {"_id": ObjectId(user_id)},
            {"$set": update_data},
            return_document=True
        )

        if not updated_user:
            logger.error("Failed to update profile")
            return jsonify({"error": "Failed to update profile"}), 500

        avatar = updated_user.get("avatar")
        logger.debug(f"Profile updated successfully: {updated_user}, avatar: {avatar}")
        return jsonify({
            "message": "Profile updated successfully",
            "user": {
                "fullName": updated_user.get("fullName"),
                "email": updated_user.get("email"),
                "role": updated_user.get("role"),
                "isActive": updated_user.get("isActive"),
                "avatar": avatar  # Return relative path
            }
        }), 200
