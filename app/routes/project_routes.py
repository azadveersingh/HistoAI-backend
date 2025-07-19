from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson import ObjectId
from datetime import datetime, timezone

from ..models import project_model
from ..extensions import mongo
from ..helpers.auth_helpers import role_required
from ..models.user import UserRoles

project_bp = Blueprint("project", __name__, url_prefix="/api/projects")

# ------------------ GET: All Projects ------------------
@project_bp.route("", methods=["GET"])
@jwt_required()
@role_required([UserRoles.ADMIN])
def fetch_projects():
    try:
        projects = project_model.get_all_projects(mongo)
        print(f"all Project{projects}")
        return jsonify({"projects":projects}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ------------------ GET: Project by ID ------------------
@project_bp.route("/<project_id>", methods=["GET"])
@jwt_required()
def get_project(project_id):
    try:
        project = project_model.get_project_by_id(mongo, project_id)
        if project:
            return jsonify(project), 200
        else:
            return jsonify({"error": "Project not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ------------------ POST: Create Project ------------------
@project_bp.route("", methods=["POST"])
@jwt_required()
@role_required([UserRoles.PM, UserRoles.BM])
def create_project():
    try:
        user_id = get_jwt_identity()
        data = request.get_json()

        name = data.get("name")
        # member_ids = data.get("memberIds", [])
        collection_ids = data.get("collectionIds", [])
        book_ids = data.get("bookIds", [])
        chat_history_id = data.get("chatHistoryId")

        if not name:
            return jsonify({"error": "Project name is required"}), 400

        project_data = {
            "name": name,
            # "memberIds": [ObjectId(m) for m in member_ids],
            "collectionIds": [ObjectId(c) for c in collection_ids],
            "bookIds": [ObjectId(b) for b in book_ids],
            "chatHistoryId": ObjectId(chat_history_id) if chat_history_id else None,
            "createdBy": ObjectId(user_id),
            "createdAt": datetime.now(timezone.utc),
            "updatedAt": datetime.now(timezone.utc),
        }

        project_id = project_model.create_project(mongo, project_data)
        return jsonify({"message": "Project created", "projectId": str(project_id)}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500

from flask import Blueprint, jsonify, request

# ------------------ GET: Projects for Current User ------------------
@project_bp.route("/my", methods=["GET"])
@jwt_required()
@role_required([UserRoles.PM, UserRoles.BM])
def get_my_projects():
    try:
        user_id = get_jwt_identity()
        projects = project_model.get_projects_by_creator(mongo, user_id)
        return jsonify({"projects": projects}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ------------------ GET: Project by ID (own only) ------------------
@project_bp.route("/my/<project_id>", methods=["GET"])
@jwt_required()
@role_required([UserRoles.PM, UserRoles.BM])
def get_own_project(project_id):
    try:
        user_id = get_jwt_identity()
        project = project_model.get_project_by_id(mongo, project_id)

        if not project:
            return jsonify({"error": "Project not found"}), 404

        if str(project.get("createdBy")) != user_id:
            return jsonify({"error": "Unauthorized"}), 403

        return jsonify(project), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ------------------ PATCH: Update Project ------------------
@project_bp.route("/<project_id>", methods=["PATCH"])
# @jwt_required()
@role_required([UserRoles.PM, UserRoles.BM])
def update_project(project_id):
    try:
        if not ObjectId.is_valid(project_id):
            return jsonify({"error": "Invalid project ID"}), 400
        
        project = project_model.get_project_by_id(mongo, project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404
        if str(project.get("createdBy")) != get_jwt_identity():
            return jsonify({"error": "Unauthorized"}), 403
        
        data = request.get_json()
        update_fields = {}
        allowed_fields = ["name", "collectionIds", "bookIds", "chatHistoryId"]

        for key in allowed_fields:
            if key in data:
                if key in ["collectionIds", "bookIds"]:
                    update_fields[key] = [ObjectId(i) for i in data[key]]
                elif key == "chatHistoryId":
                    update_fields[key] = ObjectId(data[key])
                else:
                    update_fields[key] = data[key]

        update_fields["updatedAt"] = datetime.now(timezone.utc)

        success = project_model.update_project(mongo, project_id, update_fields)
        if success:
            return jsonify({"message": "Project updated successfully"}), 200
        else:
            return jsonify({"error": "Project not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ------------------ DELETE: Delete Project ------------------
@project_bp.route("/<project_id>", methods=["DELETE"])
@jwt_required()
@role_required([UserRoles.PM, UserRoles.BM])
def delete_project(project_id):
    try:
        if not ObjectId.is_valid(project_id):
            return jsonify({"error": "Invalid project ID"}), 400
        
        project = project_model.get_project_by_id(mongo, project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404
        if str(project.get("createdBy")) != get_jwt_identity():
            return jsonify({"error": "Unauthorized"}), 403
        
        deleted = project_model.delete_project(mongo, project_id)
        if deleted:
            return jsonify({"message": "Project deleted successfully"}), 200
        else:
            return jsonify({"error": "Project not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ------------------ GET: Projects where user is a member ------------------
@project_bp.route("/member", methods=["GET"])
@jwt_required()
@role_required([UserRoles.USER])
def get_member_projects():
    try:
        user_id = get_jwt_identity()
        projects = project_model.get_projects_by_member(mongo, user_id)
        return jsonify({"projects": projects}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500