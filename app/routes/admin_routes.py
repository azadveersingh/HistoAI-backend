from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required
from bson.objectid import ObjectId
from datetime import datetime

from ..extensions import mongo
from ..models.user import User, UserRoles
from ..helpers.auth_helpers import role_required


import logging

logger = logging.getLogger(__name__)

admin_bp = Blueprint("admin", __name__, url_prefix="/api/admin")

# View all users (accessible to admin, pm, bm)
@admin_bp.route("/users", methods=["GET"])
@jwt_required()
@role_required([UserRoles.ADMIN, UserRoles.PM, UserRoles.BM])
def list_all_users():
    try:
        users = User.get_all_users()
        return jsonify(users), 200
    except Exception as e:
        logger.error(f"Error fetching users: {str(e)}")
        return jsonify({"message": "Failed to fetch users"}), 500


# -----------------------------------------------Activate/Deactivate User by Admin---------------------------------------------------
@admin_bp.route("/users/<user_id>", methods=["PATCH"])
@jwt_required()
@role_required([UserRoles.ADMIN])
def toggle_user_status(user_id):
    try:
        if not ObjectId.is_valid(user_id):
            return jsonify({"message": "Invalid user ID"}), 400

        data = request.get_json()
        if not data or "isActive" not in data:
            return jsonify({"message": "Missing 'isActive' in request body"}), 400

        is_active = data.get("isActive")
        if is_active not in [0, 1, True, False]:
            return jsonify({"message": "isActive must be 0/1 or true/false"}), 400

        user = User.find_by_id(user_id)
        if not user:
            return jsonify({"message": "User not found"}), 404

        # Prevent deactivation of admin accounts
        if user.get("role") == UserRoles.ADMIN and not is_active:
            return jsonify({"message": "Admins cannot be deactivated"}), 403

        # Update user status
        mongo.db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {
                "isActive": bool(is_active),
                "updatedAt": datetime.utcnow(),
                "lastLogin": datetime.utcnow(),
                "loginAttempts": 0
            }}
        )

        updated_user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
        updated_user["_id"] = str(updated_user["_id"])

        return jsonify({
            "message": "User status updated successfully",
            "user": {
                "_id": updated_user["_id"],
                "fullName": updated_user.get("fullName"),
                "email": updated_user.get("email"),
                "role": updated_user.get("role"),
                "isActive": updated_user.get("isActive")
            }
        }), 200

    except Exception as e:
        logger.error(f"Error updating user status: {str(e)}")
        return jsonify({"message": "Server error", "error": str(e)}), 500

# ---------------------------------------------------------------Change Roles------------------------------------------------


@admin_bp.route("/users/<user_id>/role", methods=["PATCH"])
@jwt_required()
@role_required([UserRoles.ADMIN])
def update_user_role(user_id):
    try:
        if not ObjectId.is_valid(user_id):
            return jsonify({"message": "Invalid user ID"}), 400

        data = request.get_json()
        new_role = data.get("role")

        # Validate against allowed roles
        if new_role not in UserRoles.values():
            return jsonify({
                "message": f"Invalid role. Allowed roles: {list(UserRoles.values())}"
            }), 400

        user = User.find_by_id(user_id)
        if not user:
            return jsonify({"message": "User not found"}), 404

        if user.get("role") == [UserRoles.ADMIN]:
            return jsonify({"message": "Cannot change role of another admin"}), 403

        mongo.db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {
                "role": new_role,
                "updatedAt": datetime.utcnow()
            }}
        )

        updated_user = mongo.db.users.find_one({"_id": ObjectId(user_id)})
        updated_user["_id"] = str(updated_user["_id"])

        return jsonify({
            "message": "User role updated successfully",
            "user": {
                "_id": updated_user["_id"],
                "fullName": updated_user.get("fullName"),
                "email": updated_user.get("email"),
                "role": updated_user.get("role"),
                "isActive": updated_user.get("isActive")
            }
        }), 200

    except Exception as e:
        logger.error(f"Error updating user role: {str(e)}")
        return jsonify({"message": "Server error", "error": str(e)}), 500
