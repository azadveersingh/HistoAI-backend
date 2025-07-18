from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from bson import ObjectId
from datetime import datetime

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
        member_ids = data.get("memberIds", [])

        if not name:
            return jsonify({"error": "Collection name is required"}), 400
        if not book_ids:
            return jsonify({"error": "At least one book is required"}), 400
        if not member_ids:
            return jsonify({"error": "At least one member is required"}), 400

        user_id = get_jwt_identity()

        doc = {
            "name": name,
            "bookIds": [ObjectId(bid) for bid in book_ids if ObjectId.is_valid(bid)],
            "createdBy": ObjectId(user_id),
            "projectId": ObjectId(project_id) if project_id and ObjectId.is_valid(project_id) else None,
            "memberIds": [ObjectId(mid) for mid in member_ids if ObjectId.is_valid(mid)],
            "createdAt": datetime.utcnow(),
            "updatedAt": datetime.utcnow()
        }

        # Step 1: Create the collection
        collection_id = collection_model.create_collection(mongo, doc)

        # Step 2: If projectId is valid, update the project's collectionIds and memberIds
        if project_id and ObjectId.is_valid(project_id):
            project_object_id = ObjectId(project_id)

            # Update the project's collectionIds and memberIds
            mongo.db["project-details"].update_one(
                {"_id": project_object_id},
                {
                    "$addToSet": {
                        "collectionIds": ObjectId(collection_id),
                        "memberIds": {
                            "$each": [ObjectId(mid) for mid in member_ids if ObjectId.is_valid(mid)]
                        }
                    }
                }
            )

        
        return jsonify({"message": "Collection created", "collectionId": str(collection_id)}), 201

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
            project_id = collection.get("projectId")
            if project_id:
                project = project_model.get_project_by_id(mongo, str(project_id))
                if not project or str(user_id) not in project.get("memberIds", []):
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
        update_fields = {}

        # Update collection name
        if "name" in data:
            update_fields["name"] = data["name"].strip()

        # Handle full bookIds replacement
        if "bookIds" in data:
            update_fields["bookIds"] = [
                ObjectId(bid) for bid in data["bookIds"] if ObjectId.is_valid(bid)
            ]

        # Add books to collection
        if "addBookIds" in data:
            add_ids = [ObjectId(bid) for bid in data["addBookIds"] if ObjectId.is_valid(bid)]
            current_books = collection.get("bookIds", [])
            update_fields["bookIds"] = list(set(current_books + add_ids))

        # Remove books from collection
        if "removeBookIds" in data:
            remove_ids = set(ObjectId(bid) for bid in data["removeBookIds"] if ObjectId.is_valid(bid))
            current_books = collection.get("bookIds", [])
            update_fields["bookIds"] = [bid for bid in current_books if bid not in remove_ids]

        update_fields["updatedAt"] = datetime.utcnow()

        success = collection_model.update_collection(mongo, collection_id, update_fields)
        if success:
            return jsonify({"message": "Collection updated"}), 200
        else:
            return jsonify({"error": "Update failed"}), 500

    except Exception as e:
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
