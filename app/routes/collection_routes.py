from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson import ObjectId
from datetime import datetime, timezone

from ..extensions import mongo
from ..models import collection_model, project_model
from ..helpers.auth_helpers import role_required
from ..models.user import UserRoles

collection_bp = Blueprint("collections", __name__, url_prefix="/api/collections")
ALLOWED_ROLES = [UserRoles.PM, UserRoles.BM]

# ---------- Create Collection ----------
@collection_bp.route("", methods=["POST"])
@jwt_required()
@role_required(ALLOWED_ROLES)
def create_collection():
    try:
        data = request.get_json()
        print(f"Collection data {data}")
        name = data.get("name", "").strip()
        book_ids = data.get("bookIds", [])
        project_id = data.get("projectId")

        if not name:
            return jsonify({"error": "Collection name is required"}), 400
        if not book_ids:
            return jsonify({"error": "At least one book is required"}), 400

        user_id = get_jwt_identity()

        doc = {
            "name": name,
            "bookIds": [ObjectId(bid) for bid in book_ids if ObjectId.is_valid(bid)],
            "createdBy": ObjectId(user_id),
            "projectId": ObjectId(project_id) if project_id and ObjectId.is_valid(project_id) else None,
            "createdAt": datetime.now(timezone.utc),
            "updatedAt": datetime.now(timezone.utc),
        }

        # Step 1: Create the collection
        collection_id = collection_model.create_collection(mongo, doc)

        # Step 2: If projectId is valid, update the project's collectionIds
        if project_id and ObjectId.is_valid(project_id):
            project_object_id = ObjectId(project_id)
            mongo.db["project-details"].update_one(
                {"_id": project_object_id},
                {
                    "$addToSet": {
                        "collectionIds": ObjectId(collection_id)
                    }
                }
            )
        
        return jsonify({"message": "Collection created", "collectionId": str(collection_id)}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- Add Collections to Project ----------
@collection_bp.route("/<project_id>/add", methods=["POST"])
@jwt_required()
@role_required(ALLOWED_ROLES)
def add_collections_to_project(project_id):
    try:
        if not ObjectId.is_valid(project_id):
            return jsonify({"error": "Invalid project ID"}), 400

        user_id = ObjectId(get_jwt_identity())
        project = project_model.get_project_by_id(mongo, project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404
        if str(project.get("createdBy")) != str(user_id):
            return jsonify({"error": "Unauthorized: Only the project creator can add collections"}), 403

        data = request.get_json()
        collection_ids = data.get("collectionIds", [])

        if not collection_ids:
            return jsonify({"error": "At least one collection ID is required"}), 400

        valid_collection_ids = [ObjectId(cid) for cid in collection_ids if ObjectId.is_valid(cid)]

        # Update the project's collectionIds
        result = mongo.db["project-details"].update_one(
            {"_id": ObjectId(project_id)},
            {
                "$addToSet": {
                    "collectionIds": {"$each": valid_collection_ids}
                },
                "$set": {"updatedAt": datetime.now(timezone.utc)}
            }
        )

        if result.modified_count > 0:
            # Update collections to set their projectId
            mongo.db["collections"].update_many(
                {"_id": {"$in": valid_collection_ids}},
                {"$set": {"projectId": ObjectId(project_id), "updatedAt": datetime.now(timezone.utc)}}
            )
            return jsonify({"message": "Collections added to project"}), 200
        else:
            return jsonify({"error": "No changes made to the project"}), 400

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- Remove Collections from Project ----------
@collection_bp.route("/<project_id>/remove", methods=["POST"])
@jwt_required()
@role_required(ALLOWED_ROLES)
def remove_collections_from_project(project_id):
    try:
        if not ObjectId.is_valid(project_id):
            return jsonify({"error": "Invalid project ID"}), 400

        user_id = ObjectId(get_jwt_identity())
        project = project_model.get_project_by_id(mongo, project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404
        if str(project.get("createdBy")) != str(user_id):
            return jsonify({"error": "Unauthorized: Only the project creator can remove collections"}), 403

        data = request.get_json()
        collection_ids = data.get("collectionIds", [])

        if not collection_ids:
            return jsonify({"error": "At least one collection ID is required"}), 400

        valid_collection_ids = [ObjectId(cid) for cid in collection_ids if ObjectId.is_valid(cid)]

        # Update the project's collectionIds by removing specified collections
        result = mongo.db["project-details"].update_one(
            {"_id": ObjectId(project_id)},
            {
                "$pull": {
                    "collectionIds": {"$in": valid_collection_ids}
                },
                "$set": {"updatedAt": datetime.now(timezone.utc)}
            }
        )

        if result.modified_count > 0:
            # Update collections to unset their projectId
            mongo.db["collections"].update_many(
                {"_id": {"$in": valid_collection_ids}},
                {"$unset": {"projectId": ""}, "$set": {"updatedAt": datetime.now(timezone.utc)}}
            )
            return jsonify({"message": "Collections removed from project"}), 200
        else:
            return jsonify({"error": "No changes made to the project"}), 400

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- Get Collections for a Project ----------
@collection_bp.route("/projects/<project_id>/collections", methods=["GET"])
@jwt_required()
@role_required(ALLOWED_ROLES)
def get_project_collections(project_id):
    try:
        if not ObjectId.is_valid(project_id):
            return jsonify({"error": "Invalid project ID"}), 400

        user_id = ObjectId(get_jwt_identity())
        project = project_model.get_project_by_id(mongo, project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404

        collections = collection_model.get_project_collections(mongo, project_id)
        return jsonify({"collections": collections}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- Get All Visible Collections ----------
@collection_bp.route("", methods=["GET"])
@jwt_required()
@role_required(ALLOWED_ROLES)
def get_all_collections():
    try:
        user_id = ObjectId(get_jwt_identity())
        user_projects = project_model.get_projects_by_member(mongo, str(user_id))
        project_ids = [ObjectId(p["_id"]) for p in user_projects]

        collections = collection_model.get_visible_collections(mongo, user_id, project_ids)
        return jsonify({"collections": collections}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- Get Collection By ID (If creator or member) ----------
@collection_bp.route("/<collection_id>", methods=["GET"])
@jwt_required()
@role_required(ALLOWED_ROLES)
def get_collection(collection_id):
    try:
        if not ObjectId.is_valid(collection_id):
            return jsonify({"error": "Invalid collection ID"}), 400

        user_id = ObjectId(get_jwt_identity())
        collection = collection_model.get_collection_by_id(mongo, collection_id)
        if not collection:
            return jsonify({"error": "Collection not found"}), 404

        # Authorization: allow if creator or project member
        if str(collection["createdBy"]) != str(user_id):
            project_ids = [ObjectId(pid) for pid in collection.get("projectIds", [])]
            if project_ids:
                project = mongo.db[PROJECT_COLLECTION].find_one({
                    "_id": {"$in": project_ids},
                    "memberIds": user_id
                })
                if not project:
                    return jsonify({"error": "Access denied"}), 403

        return jsonify({"collection": collection}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- Update Collection (Only Creator) ----------
@collection_bp.route("/<collection_id>", methods=["PATCH"])
@jwt_required()
@role_required(ALLOWED_ROLES)
def update_collection(collection_id):
    try:
        if not ObjectId.is_valid(collection_id):
            return jsonify({"error": "Invalid collection ID"}), 400

        user_id = ObjectId(get_jwt_identity())
        collection = collection_model.get_collection_by_id(mongo, collection_id)

        if not collection:
            return jsonify({"error": "Collection not found"}), 404
        if str(collection["createdBy"]) != str(user_id):
            return jsonify({"error": "Only the creator can update this collection"}), 403

        data = request.get_json()
        print(f"Update collection data: {data}")
        update_fields = {}

        if "name" in data:
            update_fields["name"] = data["name"].strip()

        if "bookIds" in data:
            update_fields["bookIds"] = [
                ObjectId(bid) for bid in data["bookIds"] if ObjectId.is_valid(bid)
            ]

        if "addBookIds" in data:
            add_ids = [ObjectId(bid) for bid in data["addBookIds"] if ObjectId.is_valid(bid)]
            current_books = [ObjectId(bid) for bid in collection.get("bookIds", []) if ObjectId.is_valid(bid)]
            update_fields["bookIds"] = list(set(current_books + add_ids))

        if "removeBookIds" in data:
            remove_ids = set(data["removeBookIds"])  # Keep as strings for comparison
            current_books = collection.get("bookIds", [])  # Already strings from serialize_collection
            update_fields["bookIds"] = [ObjectId(bid) for bid in current_books if bid not in remove_ids and ObjectId.is_valid(bid)]
            print(f"Removing book IDs: {remove_ids}, New bookIds: {update_fields['bookIds']}")

        update_fields["updatedAt"] = datetime.now(timezone.utc)

        success = collection_model.update_collection(mongo, collection_id, update_fields)
        print(f"Update result: modified_count={success}")
        if success:
            return jsonify({"message": "Collection updated"}), 200
        else:
            return jsonify({"error": "Update failed, no changes made"}), 500

    except Exception as e:
        print(f"Error in update_collection: {str(e)}")
        return jsonify({"error": str(e)}), 500

# ---------- Delete Collection (Only Creator) ----------
@collection_bp.route("/<collection_id>", methods=["DELETE"])
@jwt_required()
@role_required(ALLOWED_ROLES)
def delete_collection(collection_id):
    try:
        if not ObjectId.is_valid(collection_id):
            return jsonify({"error": "Invalid collection ID"}), 400

        user_id = ObjectId(get_jwt_identity())
        collection = collection_model.get_collection_by_id(mongo, collection_id)
        if not collection:
            return jsonify({"error": "Collection not found"}), 404
        if str(collection["createdBy"]) != str(user_id):
            return jsonify({"error": "Only the creator can delete this collection"}), 403

        success = collection_model.delete_collection(mongo, collection_id)
        if success:
            return jsonify({"message": "Collection deleted"}), 200
        else:
            return jsonify({"error": "Delete failed"}), 500

    except Exception as e:
        return jsonify({"error": str(e)}), 500