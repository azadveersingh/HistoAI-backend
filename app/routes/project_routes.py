from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson import ObjectId
from datetime import datetime

from ..models import project_model, user
from ..extensions import mongo
from ..helpers.auth_helpers import role_required
from ..models.user import UserRoles

project_bp = Blueprint("project", __name__, url_prefix="/api/projects")

# ------------------ GET: All Projects ------------------
@project_bp.route("", methods=["GET"])
# @jwt_required()
def fetch_projects():
    try:
        projects = project_model.get_all_projects(mongo)
        print(f"all Project{projects}")
        return jsonify({"projects":projects}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ------------------ GET: Project by ID ------------------
@project_bp.route("/<project_id>", methods=["GET"])
# @jwt_required()
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
        member_ids = data.get("memberIds", [])
        collection_ids = data.get("collectionIds", [])
        book_ids = data.get("bookIds", [])
        chat_history_id = data.get("chatHistoryId")

        if not name:
            return jsonify({"error": "Project name is required"}), 400

        project_data = {
            "name": name,
            "memberIds": [ObjectId(m) for m in member_ids],
            "collectionIds": [ObjectId(c) for c in collection_ids],
            "bookIds": [ObjectId(b) for b in book_ids],
            "chatHistoryId": ObjectId(chat_history_id) if chat_history_id else None,
            "createdBy": ObjectId(user_id),
            "createdAt": datetime.utcnow(),
            "updatedAt": datetime.utcnow(),
        }

        project_id = project_model.create_project(mongo, project_data)
        return jsonify({"message": "Project created", "projectId": str(project_id)}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ------------------ PATCH: Update Project ------------------
@project_bp.route("/<project_id>", methods=["PATCH"])
@jwt_required()
@role_required([UserRoles.PM, UserRoles.BM])
def update_project(project_id):
    try:
        if not ObjectId.is_valid(project_id):
            return jsonify({"error": "Invalid project ID"}), 400

        data = request.get_json()
        update_fields = {}
        allowed_fields = ["name", "memberIds", "collectionIds", "bookIds", "chatHistoryId"]

        for key in allowed_fields:
            if key in data:
                if key in ["memberIds", "collectionIds", "bookIds"]:
                    update_fields[key] = [ObjectId(i) for i in data[key]]
                elif key == "chatHistoryId":
                    update_fields[key] = ObjectId(data[key])
                else:
                    update_fields[key] = data[key]

        update_fields["updatedAt"] = datetime.utcnow()

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

        deleted = project_model.delete_project(mongo, project_id)
        if deleted:
            return jsonify({"message": "Project deleted successfully"}), 200
        else:
            return jsonify({"error": "Project not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500




# from flask import Blueprint, jsonify, request
# from bson import ObjectId
# from ..models import project_model
# from ..extensions import mongo

# project_bp = Blueprint("project", __name__)

# @project_bp.route("/api/projects", methods=["GET"])
# def fetch_projects():
#     try:
#         projects = project_model.get_all_projects(mongo)
#         print(f"all Project{projects}")
#         return jsonify({"projects":projects}), 200
#     except Exception as e:
#         return jsonify({"error": str(e)}), 500

# @project_bp.route("/api/projects/<project_id>", methods=["GET"])
# def get_project(project_id):
#     try:
#         project = project_model.get_project_by_id(mongo, project_id)
#         if project:
#             return jsonify(project), 200
#         else:
#             return jsonify({"error": "Project not found"}), 404
#     except Exception as e:
#         return jsonify({"error": str(e)}), 500
    
