from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from werkzeug.utils import secure_filename
from bson import ObjectId
from datetime import datetime, timezone
import os

from ..models import book_model, project_model
from ..extensions import mongo
from ..helpers.auth_helpers import role_required
from ..models.user import UserRoles
from ..helpers.file_helpers import allowed_file, create_pdf_preview
from PyPDF2 import PdfReader

book_bp = Blueprint("books", __name__, url_prefix="/api/books")

MAX_TOTAL_UPLOAD_MB = 150
UPLOAD_DIR = "uploads/books"

# ---------- 1. Upload Books (PDFs) ----------
@book_bp.route("/upload", methods=["POST"])
@jwt_required()
@role_required([UserRoles.BM])
def upload_books():
    try:
        if 'files' not in request.files:
            return jsonify({"error": "No files part in request"}), 400

        files = request.files.getlist("files")
        if not files:
            return jsonify({"error": "No files selected"}), 400


        # Get metadata arrays
        book_names = request.form.getlist("bookName")
        authors = request.form.getlist("author")
        editions = request.form.getlist("edition")

        # Validate metadata length matches files
        if len(book_names) != len(files) or len(authors) != len(files):
            return jsonify({"error": "Number of bookName/author entries must match number of files"}), 400

        os.makedirs(UPLOAD_DIR, exist_ok=True)
        user_id = get_jwt_identity()
        uploaded = []

        for i, file in enumerate(files):
            if not allowed_file(file.filename):
                continue

            # Get metadata for this file
            book_name = book_names[i].strip().upper()
            author = authors[i].strip().upper()
            edition = editions[i].strip().upper() if i < len(editions) else ""

            if not book_name or not author:
                return jsonify({"error": f"bookName and author are required for file {file.filename}"}), 400

            # Check for duplicate bookName
            existing = mongo.db.books.find_one({"bookName": book_name})
            if existing:
                return jsonify({"error": f"Book name '{book_name}' already exists"}), 409

            # Save file
            filename = secure_filename(file.filename)
            filepath = os.path.join(UPLOAD_DIR, filename)
            file.save(filepath)

            # Count actual number of pages
            try:
                with open(filepath, "rb") as f:
                    reader = PdfReader(f)
                    pages = len(reader.pages)
            except Exception:
                pages = 0

            # Generate preview image
            preview_filename = create_pdf_preview(filepath)
            preview_rel_path = os.path.join("uploads/books", preview_filename)

            # Construct metadata
            book_doc = {
                "fileName": filename,
                "bookName": book_name,
                "author": author,
                "edition": edition,
                "fileSize": os.path.getsize(filepath),
                "pages": pages,
                "visibility": "private",
                "frontPageImagePath": preview_filename,
                "previewUrl": preview_rel_path,
                "ocrProcessId": None,
                "createdBy": ObjectId(user_id),
                "createdAt": datetime.now(timezone.utc),
                "updatedAt": datetime.now(timezone.utc)
            }

            inserted_id = book_model.create_book(mongo, book_doc)

            uploaded.append({
                "bookId": inserted_id,
                "fileName": filename,
                "bookName": book_name,
                "author": author,
                "edition": edition,
                "pages": pages,
                "previewUrl": f"/{preview_rel_path}"
            })

        return jsonify({
            "message": "Books uploaded and metadata stored",
            "files": uploaded
        }), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- 2. Add Books to Project ----------
@book_bp.route("/<project_id>/add", methods=["POST"])
@jwt_required()
@role_required([UserRoles.PM, UserRoles.BM])
def add_books_to_project(project_id):
    try:
        if not ObjectId.is_valid(project_id):
            return jsonify({"error": "Invalid project ID"}), 400

        user_id = ObjectId(get_jwt_identity())
        project = project_model.get_project_by_id(mongo, project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404
        if str(project.get("createdBy")) != str(user_id):
            return jsonify({"error": "Unauthorized: Only the project creator can add books"}), 403

        data = request.get_json()
        book_ids = data.get("bookIds", [])

        if not book_ids:
            return jsonify({"error": "At least one book ID is required"}), 400

        valid_book_ids = [ObjectId(bid) for bid in book_ids if ObjectId.is_valid(bid)]

        # Update the project's bookIds
        result = mongo.db["project-details"].update_one(
            {"_id": ObjectId(project_id)},
            {
                "$addToSet": {
                    "bookIds": {"$each": valid_book_ids}
                },
                "$set": {"updatedAt": datetime.now(timezone.utc)}
            }
        )

        if result.modified_count > 0:
            return jsonify({"message": "Books added to project"}), 200
        else:
            return jsonify({"error": "No changes made to the project"}), 400

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- 3. Remove Books from Project ----------
@book_bp.route("/<project_id>/remove", methods=["POST"])
@jwt_required()
@role_required([UserRoles.PM, UserRoles.BM])
def remove_books_from_project(project_id):
    try:
        if not ObjectId.is_valid(project_id):
            return jsonify({"error": "Invalid project ID"}), 400

        user_id = ObjectId(get_jwt_identity())
        project = project_model.get_project_by_id(mongo, project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404
        if str(project.get("createdBy")) != str(user_id):
            return jsonify({"error": "Unauthorized: Only the project creator can remove books"}), 403

        data = request.get_json()
        book_ids = data.get("bookIds", [])

        if not book_ids:
            return jsonify({"error": "At least one book ID is required"}), 400

        valid_book_ids = [ObjectId(bid) for bid in book_ids if ObjectId.is_valid(bid)]

        # Update the project's bookIds by removing specified books
        result = mongo.db["project-details"].update_one(
            {"_id": ObjectId(project_id)},
            {
                "$pull": {
                    "bookIds": {"$in": valid_book_ids}
                },
                "$set": {"updatedAt": datetime.now(timezone.utc)}
            }
        )

        if result.modified_count > 0:
            return jsonify({"message": "Books removed from project"}), 200
        else:
            return jsonify({"error": "No changes made to the project"}), 400

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- 4. Get All Books (Admin/BM/PM/User) ----------
@book_bp.route("/", methods=["GET"])
@jwt_required()
@role_required([UserRoles.ADMIN, UserRoles.BM, UserRoles.PM, UserRoles.USER])
def get_all_books():
    try:
        books = book_model.get_all_books(mongo)
        return jsonify({"books": books}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- 5. Get Books for a Project ----------
@book_bp.route("/projects/<project_id>/books", methods=["GET"])
@jwt_required()
@role_required([UserRoles.ADMIN, UserRoles.BM, UserRoles.PM, UserRoles.USER])
def get_project_books(project_id):
    try:
        if not ObjectId.is_valid(project_id):
            return jsonify({"error": "Invalid project ID"}), 400

        user_id = ObjectId(get_jwt_identity())
        project = project_model.get_project_by_id(mongo, project_id)
        if not project:
            return jsonify({"error": "Project not found"}), 404

        books = book_model.get_books_by_project(mongo, project_id)
        return jsonify({"books": books}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- 6. Delete Book ----------
@book_bp.route("/<book_id>", methods=["DELETE"])
@jwt_required()
@role_required([UserRoles.BM])
def delete_book(book_id):
    try:
        if not ObjectId.is_valid(book_id):
            return jsonify({"error": "Invalid book ID"}), 400

        existing = book_model.get_book_by_id(mongo, book_id)
        if not existing:
            return jsonify({"error": "Book not found"}), 404

        deleted = book_model.delete_book(mongo, book_id)
        if deleted:
            return jsonify({"message": "Book deleted successfully"}), 200
        else:
            return jsonify({"error": "Failed to delete book"}), 500

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ---------- 7. Update Book Visibility ----------
@book_bp.route("/<book_id>/visibility", methods=["PATCH"])
@jwt_required()
@role_required([UserRoles.BM])
def update_book_visibility(book_id):
    try:
        if not ObjectId.is_valid(book_id):
            return jsonify({"error": "Invalid book ID"}), 400

        data = request.get_json()
        new_visibility = data.get("visibility", "").lower()

        if new_visibility not in ["private", "public"]:
            return jsonify({"error": "Invalid visibility. Use 'private' or 'public'"}), 400

        success = book_model.update_book(mongo, book_id, {"visibility": new_visibility})

        if success:
            return jsonify({"message": f"Book visibility updated to '{new_visibility}'"}), 200
        else:
            return jsonify({"error": "Failed to update visibility"}), 500

    except Exception as e:
        return jsonify({"error": str(e)}), 500