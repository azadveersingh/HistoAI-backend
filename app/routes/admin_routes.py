from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson.objectid import ObjectId
from datetime import datetime, timezone

from ..extensions import mongo
from ..models.user import User, UserRoles
from ..helpers.auth_helpers import role_required
from ..models import project_model

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

# Fetch members for a project
@admin_bp.route("/projects/<project_id>/members", methods=["GET"])
@jwt_required()
@role_required([UserRoles.ADMIN, UserRoles.PM, UserRoles.BM, UserRoles.USER])
def get_project_members(project_id):
    try:
        if not ObjectId.is_valid(project_id):
            return jsonify({"error": "Invalid project ID"}), 400

        project = project_model.get_project_by_id(mongo, project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404

        member_ids = project.get("memberIds", [])
        if not member_ids:
            return jsonify({"members": []}), 200

        members = User.find_by_ids(member_ids)
        return jsonify({"members": members}), 200

    except Exception as e:
        logger.error(f"Error fetching project members: {str(e)}")
        return jsonify({"error": str(e)}), 500

# Add members to a project
@admin_bp.route("/projects/<project_id>/members", methods=["POST"])
@jwt_required()
@role_required([UserRoles.PM, UserRoles.BM])
def add_members_to_project(project_id):
    try:
        if not ObjectId.is_valid(project_id):
            return jsonify({"error": "Invalid project ID"}), 400

        user_id = ObjectId(get_jwt_identity())
        project = project_model.get_project_by_id(mongo, project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404
        if str(project.get("createdBy")) != str(user_id):
            return jsonify({"error": "Unauthorized: Only the project creator can add members"}), 403

        data = request.get_json()
        member_ids = data.get("memberIds", [])

        if not member_ids:
            return jsonify({"error": "At least one member ID is required"}), 400

        valid_member_ids = [ObjectId(mid) for mid in member_ids if ObjectId.is_valid(mid)]

        # Update the project's memberIds
        result = mongo.db["project-details"].update_one(
            {"_id": ObjectId(project_id)},
            {
                "$addToSet": {
                    "memberIds": {"$each": valid_member_ids}
                },
                "$set": {"updatedAt": datetime.now(timezone.utc)}
            }
        )

        if result.modified_count > 0:
            return jsonify({"message": "Members added to project"}), 200
        else:
            return jsonify({"error": "No changes made to the project"}), 400

    except Exception as e:
        logger.error(f"Error adding members to project: {str(e)}")
        return jsonify({"error": str(e)}), 500

# Remove members from a project
@admin_bp.route("/projects/<project_id>/members/remove", methods=["POST"])
@jwt_required()
@role_required([UserRoles.PM, UserRoles.BM])
def remove_members_from_project(project_id):
    try:
        if not ObjectId.is_valid(project_id):
            return jsonify({"error": "Invalid project ID"}), 400

        user_id = ObjectId(get_jwt_identity())
        project = project_model.get_project_by_id(mongo, project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404
        if str(project.get("createdBy")) != str(user_id):
            return jsonify({"error": "Unauthorized: Only the project creator can remove members"}), 403

        data = request.get_json()
        member_ids = data.get("memberIds", [])

        if not member_ids:
            return jsonify({"error": "At least one member ID is required"}), 400

        valid_member_ids = [ObjectId(mid) for mid in member_ids if ObjectId.is_valid(mid)]

        # Update the project's memberIds by removing specified members
        result = mongo.db["project-details"].update_one(
            {"_id": ObjectId(project_id)},
            {
                "$pull": {
                    "memberIds": {"$in": valid_member_ids}
                },
                "$set": {"updatedAt": datetime.now(timezone.utc)}
            }
        )

        if result.modified_count > 0:
            return jsonify({"message": "Members removed from project"}), 200
        else:
            return jsonify({"error": "No changes made to the project"}), 400

    except Exception as e:
        logger.error(f"Error removing members from project: {str(e)}")
        return jsonify({"error": str(e)}), 500

# Activate/Deactivate User by Admin
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
                "updatedAt": datetime.now(timezone.utc),
                "lastLogin": datetime.now(timezone.utc),
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

# Change User Role
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

        if user.get("role") == UserRoles.ADMIN:
            return jsonify({"message": "Cannot change role of another admin"}), 403

        mongo.db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {
                "role": new_role,
                "updatedAt": datetime.now(timezone.utc)
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