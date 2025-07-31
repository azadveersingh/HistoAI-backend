from flask import Blueprint, jsonify, send_file
from flask_jwt_extended import jwt_required, get_jwt_identity
from ..models import book_model
from ..models.user import User
from bson.objectid import ObjectId
import os
import logging
import mimetypes
from datetime import datetime
from ..config import Config
from ..extensions import mongo  # Import the MongoDB instance

bp = Blueprint("file_serve_bp", __name__)

logger = logging.getLogger(__name__)

@bp.route("/Uploads/book/<path:filename>")
@jwt_required()  # Enable authentication to match frontend
def serve_book(filename):
    book_dir = Config.BOOK_UPLOAD_DIR
    file_path = os.path.join(book_dir, filename)
    if not os.path.exists(file_path):
        logger.error(f"Book file not found: {file_path}")
        return jsonify({"error": f"File not found: {filename}"}), 404

    book_id = filename.split("/")[0]
    try:
        book = book_model.get_book_by_id(mongo, book_id)
    except ValueError:
        logger.error(f"Invalid book ID: {book_id}")
        return jsonify({"error": f"Invalid book ID: {book_id}"}), 400

    if not book:
        logger.error(f"Book not found in database for ID: {book_id}")
        return jsonify({"error": f"Book not found for ID: {book_id}"}), 404

    return send_file(file_path, mimetype=mimetypes.guess_type(file_path)[0] or "application/octet-stream")


@bp.route("/uploads/book/<path:filename>/download")
@jwt_required()
def download_book(filename):
    book_dir = Config.BOOK_UPLOAD_DIR
    file_path = os.path.join(book_dir, filename)
    if not os.path.exists(file_path):
        logger.error(f"Book file not found for download: {file_path}")
        return jsonify({"error": f"File not found: {filename}"}), 404
    return send_file(file_path, as_attachment=True, download_name=os.path.basename(file_path))

@bp.route("/avatars/<path:filename>")
@jwt_required()
def serve_avatar(filename):
    avatar_dir = Config.AVATAR_UPLOAD_DIR
    file_path = os.path.join(avatar_dir, filename)
    if not os.path.exists(file_path):
        logger.error(f"Avatar file not found: {file_path}")
        return jsonify({"error": f"File not found: {filename}"}), 404
    return send_file(file_path)
