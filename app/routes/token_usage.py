from flask import Blueprint, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
import os
import json
from ..extensions import mongo

bp = Blueprint("token_usage", __name__, url_prefix="/api")


@bp.route("/token_usage", methods=["GET"])
@jwt_required()
def get_user_token_usage():
    """Get total tokens used by the logged-in user along with book-wise usage"""
    user_id = get_jwt_identity()
    total_tokens_used, book_details = calculate_tokens_for_user(user_id)
    
    return jsonify({
        "user_id": user_id,
        "total_tokens_used": total_tokens_used,
        "books": book_details
    }), 200

@bp.route("/all-users-tokens", methods=["GET"])
@jwt_required()
def get_all_users_token_usage():
    """Admin route to get all users, their total tokens, and book-wise usage"""
    user_ids = mongo.db.uploads.distinct("user_id")
    
    user_token_data = []

    for user_id in user_ids:
        total_tokens_used, book_details = calculate_tokens_for_user(user_id)
        user_token_data.append({
            "user_id": user_id,
            "total_tokens_used": total_tokens_used,
            "books": book_details
        })

    return jsonify({"users": user_token_data}), 200


def calculate_tokens_for_user(user_id):
    """Helper function to calculate total tokens used by a user and book-wise token usage"""
    uploads = mongo.db.uploads.find(
        {"user_id": user_id},
        {"structured_data_path": 1, "filename": 1, "_id": 1}  # Include book_id and name
    )

    total_tokens_used = 0
    book_details = []

    for upload in uploads:
        book_id = str(upload["_id"])
        filename = upload.get("filename", "Unknown Book")
        structured_data_path = upload.get("structured_data_path")

        if not structured_data_path:
            continue

        full_path = os.path.join(current_app.config["UPLOAD_FOLDER"], structured_data_path)

        if not os.path.exists(full_path):
            print(f"Warning: File {full_path} not found.")
            continue

        try:
            with open(full_path, "r", encoding="utf-8") as json_file:
                structured_data = json.load(json_file)
                token_count = len(structured_data)
                total_tokens_used += token_count
                book_details.append({
                    "book_id": book_id,
                    "book_name": filename,
                    "tokens_used": token_count
                })
        except Exception as e:
            print(f"Error reading {full_path}: {e}")

    return total_tokens_used, book_details

