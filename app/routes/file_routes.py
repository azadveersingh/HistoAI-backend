from flask import Blueprint, send_from_directory, current_app,request, jsonify, request
import os
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..extensions import mongo, socketio
from ..models.file_handling import rename_book, delete_book

bp = Blueprint("file_bp",__name__, url_prefix="/api")

@bp.route("/uploads/<path:foldername>/<path:filename>")
def serve_file(foldername, filename):
    """
    Serve the requested file (PDF or image) from the uploads directory.
    """
    upload_folder = current_app.config["UPLOAD_FOLDER"]
    file_path = os.path.join(upload_folder, foldername, filename)

    if not os.path.exists(file_path):
        return {"error": "File not found"}, 404

    return send_from_directory(os.path.dirname(file_path), os.path.basename(file_path))


@bp.route("/rename-file", methods=["PUT"])
@jwt_required()
def rename_upload():
    """API route to rename a book and update all related files."""
    user_id = get_jwt_identity()
    data = request.get_json()
    book_id = data.get("book_id")
    new_name = data.get("new_name")

    if not book_id or not new_name:
        return jsonify({"error": "Missing required parameters"}), 400

    response, status = rename_book(mongo, book_id, new_name, user_id)
    socketio.emit("rename_status", response)

    return jsonify(response), status

@bp.route("/delete-file", methods=["DELETE"])
@jwt_required()
def delete_upload():
    """API route to delete a book and its associated folder."""
    user_id = get_jwt_identity()
    data = request.get_json()
    book_id = data.get("book_id")

    if not book_id:
        return jsonify({"error": "Missing book_id"}), 400

    response, status = delete_book(mongo, book_id, user_id)
    socketio.emit("delete_status", response)

    return jsonify(response), status

