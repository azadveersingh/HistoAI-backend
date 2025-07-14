from flask import Blueprint, jsonify, request
from bson import ObjectId
from ..models import project_model
from ..extensions import mongo

project_bp = Blueprint("project", __name__)

@project_bp.route("/api/projects", methods=["GET"])
def fetch_projects():
    try:
        projects = project_model.get_all_projects(mongo)
        print(f"all Project{projects}")
        return jsonify({"projects":projects}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@project_bp.route("/api/projects/<project_id>", methods=["GET"])
def get_project(project_id):
    try:
        project = project_model.get_project_by_id(mongo, project_id)
        if project:
            return jsonify(project), 200
        else:
            return jsonify({"error": "Project not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    

# ------------------------------------------------------------- Only for Project Manager-------------------------------------------------------
# @project_bp.route("/api/projects", methods=["POST"])
# def add_project():
#     try:
#         data = request.json
#         # Convert IDs from string to ObjectId
#         data["memberIds"] = [ObjectId(mid) for mid in data.get("memberIds", [])]
#         data["collectionIds"] = [ObjectId(cid) for cid in data.get("collectionIds", [])]
#         data["bookIds"] = [ObjectId(bid) for bid in data.get("bookIds", [])]
#         if "chatHistoryId" in data:
#             data["chatHistoryId"] = ObjectId(data["chatHistoryId"])
#         if "createdBy" in data:
#             data["createdBy"] = ObjectId(data["createdBy"])

#         project_id = project_model.create_project(mongo, data)
#         return jsonify({"message": "Project created", "projectId": project_id}), 201
#     except Exception as e:
#         return jsonify({"error": str(e)}), 500
