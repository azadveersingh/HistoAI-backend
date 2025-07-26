from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from werkzeug.utils import secure_filename
from bson import ObjectId
from datetime import datetime, timezone, timedelta
import os
import smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv
from ..models.user import User, UserRoles
from ..models import book_model, project_model, ocr_model
from ..extensions import mongo
from ..helpers.auth_helpers import role_required
from ..helpers.file_helpers import allowed_file, create_pdf_preview
from PyPDF2 import PdfReader

# Load email config from .env
load_dotenv()
EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_PORT = int(os.getenv("EMAIL_PORT"))
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")

book_bp = Blueprint("books", __name__, url_prefix="/api/books")

MAX_TOTAL_UPLOAD_MB = 150
UPLOAD_DIR = "Uploads/books"

def send_deletion_email(recipients, book_details_list, deleter_name, deleter_role, deletion_time):
    try:
        book_count = len(book_details_list)
        book_term = "book" if book_count == 1 else "books"
        verb = "has" if book_count == 1 else "have"
        
        # Format deletion timestamp (IST: UTC+5:30)
        ist_time = deletion_time + timedelta(hours=5, minutes=30)
        deletion_str = ist_time.strftime("%A, %B %d, %Y, at %I:%M %p IST")
        
        # Generate HTML list of books with optional second author
        book_list_items = "".join(
            f"<li style='margin-bottom: 10px; color: #FF0000;'>Book: {book['bookName']}, Author: {book['author']}"
            f"{', Co-Author: ' + book['author2'] if book['author2'] != 'N/A' else ''}, Edition: {book['edition']}, Uploaded by: {book['uploaderName']}</li>"
            for book in book_details_list
        )

        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; background-color: #f4f4f4; padding: 30px; margin: 0;">
            <div style="max-width: 600px; margin: auto; background-color: #ffffff; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); overflow: hidden;">
                <div style="background-color: #003366; padding: 20px; text-align: center;">
                    <img src="https://raw.githubusercontent.com/Coding-with-Gaurav/KTB-LLM-web/refs/heads/main/graphiti1.png" alt="HistoAI Logo" style="max-height: 50px; display: block; margin: auto;" />
                    <h2 style="color: white; margin: 10px 0 0; font-size: 24px;">Book Deletion Notification</h2>
                </div>
                <div style="padding: 30px; color: #333; font-size: 16px; line-height: 1.6;">
                    <p style="margin: 0 0 15px;">Dear {{recipient_name}} ({{recipient_role}}),</p>
                    <p style="margin: 0 0 15px;">We would like to notify you that the following {book_term} {verb} been deleted by <span style="color: #0000FF;">{deleter_name} ({deleter_role})</span> on {deletion_str}:</p>
                    <ul style="list-style-type: disc; padding-left: 20px; margin: 0 0 15px;">
                        {book_list_items}
                    </ul>
                    <p style="margin: 0;">Regards,<br><strong>HistoAI</strong></p>
                </div>
                <div style="background-color: #f1f1f1; text-align: center; padding: 15px; font-size: 12px; color: #777;">
                    © {datetime.now(timezone.utc).year} HistoAI. All rights reserved.
                </div>
            </div>
        </body>
        </html>
        """
        for recipient in recipients:
            msg = MIMEText(
                html_content.format(
                    recipient_name=recipient["fullName"],
                    recipient_role=recipient["role"].capitalize(),
                    book_term=book_term,
                    verb=verb,
                    deleter_name=deleter_name,
                    deleter_role=deleter_role.capitalize()
                ),
                "html"
            )
            msg["Subject"] = "Book Deletion Notification"
            msg["From"] = EMAIL_USER
            msg["To"] = recipient["email"]

            smtp = smtplib.SMTP(EMAIL_HOST, EMAIL_PORT)
            smtp.starttls()
            smtp.login(EMAIL_USER, EMAIL_PASS)
            smtp.send_message(msg)
            smtp.quit()

    except Exception as e:
        print(f"Failed to send deletion email: {str(e)}")

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

        book_names = request.form.getlist("bookName")
        authors = request.form.getlist("author")
        authors2 = request.form.getlist("author2")  # Optional second author
        editions = request.form.getlist("edition")

        # Validate that bookName and primary author match the number of files
        if len(book_names) != len(files) or len(authors) != len(files):
            return jsonify({"error": "Number of bookName and primary author entries must match number of files"}), 400

        os.makedirs(UPLOAD_DIR, exist_ok=True)
        user_id = get_jwt_identity()
        uploaded = []

        for i, file in enumerate(files):
            if not allowed_file(file.filename):
                continue

            book_name = book_names[i].strip().upper()
            author = authors[i].strip().upper()
            author2 = authors2[i].strip().upper() if i < len(authors2) and authors2[i].strip() else ""  # Optional second author
            edition = editions[i].strip().upper() if i < len(editions) else ""

            if not book_name or not author:
                return jsonify({"error": f"bookName and primary author are required for file {file.filename}"}), 400

            existing = mongo.db.books.find_one({"bookName": book_name})
            if existing:
                return jsonify({"error": f"Book name '{book_name}' already exists"}), 409

            filename = secure_filename(file.filename)
            filepath = os.path.join(UPLOAD_DIR, filename)
            file.save(filepath)

            try:
                with open(filepath, "rb") as f:
                    reader = PdfReader(f)
                    pages = len(reader.pages)
            except Exception:
                pages = 0

            preview_filename = create_pdf_preview(filepath)
            preview_rel_path = os.path.join("uploads/books", preview_filename)

            book_doc = {
                "fileName": filename,
                "bookName": book_name,
                "author": author,
                "author2": author2,  # Optional second author
                "edition": edition,
                "fileSize": os.path.getsize(filepath),
                "pages": pages,
                "visibility": "private",  # Always private initially
                "frontPageImagePath": preview_filename,
                "previewUrl": preview_rel_path,
                "ocrProcessId": None,  # Will be updated after OCR process creation
                "createdBy": ObjectId(user_id),
                "createdAt": datetime.now(timezone.utc),
                "updatedAt": datetime.now(timezone.utc)
            }

            inserted_id = book_model.create_book(mongo, book_doc)
            ocr_process_id = ocr_model.create_ocr_process(mongo, inserted_id)
            book_model.update_book(mongo, inserted_id, {"ocrProcessId": ObjectId(ocr_process_id)})

            uploaded.append({
                "bookId": inserted_id,
                "fileName": filename,
                "bookName": book_name,
                "author": author,
                "author2": author2,
                "edition": edition,
                "pages": pages,
                "previewUrl": f"/{preview_rel_path}"
            })

        return jsonify({
            "message": "Books uploaded and OCR processes started",
            "files": uploaded
        }), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@book_bp.route("/<book_id>/update", methods=["PATCH"])
@jwt_required()
@role_required([UserRoles.BM])
def update_book_details(book_id):
    try:
        if not ObjectId.is_valid(book_id):
            return jsonify({"error": "Invalid book ID"}), 400

        user_id = ObjectId(get_jwt_identity())
        book = book_model.get_book_by_id(mongo, book_id)
        if not book:
            return jsonify({"error": "Book not found"}), 404
        if str(book.get("createdBy")) != str(user_id):
            return jsonify({"error": "Unauthorized: Only the book uploader can update details"}), 403

        data = request.get_json()
        update_fields = {}

        # Validate and add bookName if provided
        if "bookName" in data and data["bookName"].strip():
            book_name = data["bookName"].strip().upper()
            existing = mongo.db.books.find_one({"bookName": book_name, "_id": {"$ne": ObjectId(book_id)}})
            if existing:
                return jsonify({"error": f"Book name '{book_name}' already exists"}), 409
            update_fields["bookName"] = book_name

        # Validate and add primary author (mandatory if provided)
        if "author" in data:
            if not data["author"].strip():
                return jsonify({"error": "Primary author cannot be empty"}), 400
            update_fields["author"] = data["author"].strip().upper()

        # Add second author (optional)
        if "author2" in data:
            update_fields["author2"] = data["author2"].strip().upper() if data["author2"].strip() else ""

        # Validate and add edition if provided
        if "edition" in data:
            update_fields["edition"] = data["edition"].strip().upper() if data["edition"].strip() else ""

        if not update_fields:
            return jsonify({"error": "No valid fields provided for update"}), 400

        success = book_model.update_book(mongo, book_id, update_fields)
        if success:
            return jsonify({"message": "Book details updated successfully"}), 200
        else:
            return jsonify({"error": "Failed to update book details"}), 500

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@book_bp.route("/<book_id>/ocr/complete", methods=["POST"])
@jwt_required()
@role_required([UserRoles.BM])
def complete_ocr_process(book_id):
    try:
        if not ObjectId.is_valid(book_id):
            return jsonify({"error": "Invalid book ID"}), 400

        user_id = ObjectId(get_jwt_identity())
        book = book_model.get_book_by_id(mongo, book_id)
        if not book:
            return jsonify({"error": "Book not found"}), 404
        if str(book.get("createdBy")) != str(user_id):
            return jsonify({"error": "Unauthorized: Only the book uploader can complete OCR"}), 403

        success = ocr_model.mark_ocr_process_complete(mongo, book_id)
        if not success:
            return jsonify({"error": "Failed to complete OCR process"}), 500

        # Update book visibility to public after OCR completion
        book_model.update_book(mongo, book_id, {"visibility": "public"})

        return jsonify({"message": "OCR process completed and book visibility set to public"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

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

        # Validate that books have completed OCR
        valid_book_ids = []
        for bid in book_ids:
            if not ObjectId.is_valid(bid):
                continue
            ocr_process = ocr_model.get_ocr_process_by_book(mongo, bid)
            if ocr_process and ocr_process["status"] == "completed":
                valid_book_ids.append(ObjectId(bid))

        if not valid_book_ids:
            return jsonify({"error": "No books with completed OCR provided"}), 400

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

@book_bp.route("/", methods=["GET"])
@jwt_required()
@role_required([UserRoles.ADMIN, UserRoles.BM, UserRoles.PM, UserRoles.USER])
def get_all_books():
    try:
        # Only return books with completed OCR
        ocr_processes = mongo.db["ocr_process"].find({"status": "completed"})
        completed_book_ids = [str(ocr_process["bookId"]) for ocr_process in ocr_processes]
        books = mongo.db["books"].find({"_id": {"$in": [ObjectId(bid) for bid in completed_book_ids]}})
        return jsonify({"books": [book_model.serialize_book(book) for book in books]}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@book_bp.route("/processing", methods=["GET"])
@jwt_required()
@role_required([UserRoles.BM])
def get_processing_books():
    try:
        ocr_processes = ocr_model.get_all_ocr_processes(mongo)
        processing_books = []
        for ocr_process in ocr_processes:
            if ocr_process["status"] != "completed":
                book = book_model.get_book_by_id(mongo, ocr_process["bookId"])
                if book:
                    book["ocrStatus"] = ocr_process["status"]
                    book["progress"] = ocr_process["progress"]
                    processing_books.append(book)
        return jsonify({"books": processing_books}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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

@book_bp.route("/<book_id>/projects", methods=["GET"])
@jwt_required()
@role_required([UserRoles.BM])
def get_projects_for_book(book_id):
    try:
        if not ObjectId.is_valid(book_id):
            return jsonify({"error": "Invalid book ID"}), 400

        # Find projects where book_id is in bookIds
        projects = mongo.db["project-details"].find({
            "bookIds": ObjectId(book_id)
        })
        project_list = [{"_id": str(project["_id"]), "name": project.get("name", "Unnamed Project")} for project in projects]

        return jsonify({"projects": project_list}), 200
    except Exception as e:
        print(f"Error in get_projects_for_book: {str(e)}")
        return jsonify({"error": str(e)}), 500

@book_bp.route("/<book_id>", methods=["DELETE"])
@jwt_required()
@role_required([UserRoles.BM])
def delete_book(book_id):
    try:
        if not ObjectId.is_valid(book_id):
            return jsonify({"error": "Invalid book ID"}), 400

        # Capture deletion time (UTC)
        deletion_time = datetime.now(timezone.utc)

        # Fetch book details
        book_detail = book_model.get_book_details_for_email(mongo, book_id, deletion_time)
        if not book_detail:
            return jsonify({"error": "Book not found"}), 404

        # Get deleter and uploader details
        deleter_id = get_jwt_identity()
        deleter = User.find_by_id(deleter_id)
        if not deleter:
            return jsonify({"error": "Deleter not found"}), 404

        uploader_id = str(mongo.db.books.find_one({"_id": ObjectId(book_id)}).get("createdBy"))
        uploader = User.find_by_id(uploader_id) if uploader_id else None

        # Get admin(s)
        admins = mongo.db.users.find({"role": UserRoles.ADMIN})
        admin_list = [{"fullName": admin.get("fullName", "Unknown"), "email": admin.get("email", ""), "role": admin.get("role", "admin")} for admin in admins]

        # Determine recipients
        recipients = admin_list
        if uploader:
            recipients.append({
                "fullName": uploader.get("fullName", "Unknown"),
                "email": uploader.get("email", ""),
                "role": uploader.get("role", "book_manager")
            })
        if uploader_id != deleter_id:
            recipients.append({
                "fullName": deleter.get("fullName", "Unknown"),
                "email": deleter.get("email", ""),
                "role": deleter.get("role", "book_manager")
            })

        # Remove duplicates by email
        unique_recipients = {recipient["email"]: recipient for recipient in recipients if recipient["email"]}.values()

        # Delete associated OCR process
        ocr_model.update_ocr_process(mongo, book_id, {"status": "failed", "errorMessage": "Book deleted"})

        # Delete book
        deleted = book_model.delete_book(mongo, book_id)
        if not deleted:
            return jsonify({"error": "Failed to delete book"}), 500

        # Send email notifications
        send_deletion_email(
            unique_recipients,
            [book_detail],
            deleter.get("fullName", "Unknown"),
            deleter.get("role", "book_manager"),
            deletion_time
        )

        return jsonify({"message": "Book deleted successfully"}), 200

    except Exception as e:
        print(f"Error in delete_book: {str(e)}")
        return jsonify({"error": str(e)}), 500

@book_bp.route("/delete", methods=["POST"])
@jwt_required()
@role_required([UserRoles.BM])
def delete_books():
    try:
        data = request.get_json()
        book_ids = data.get("bookIds", [])
        if not book_ids:
            return jsonify({"error": "At least one book ID is required"}), 400

        valid_book_ids = [ObjectId(bid) for bid in book_ids if ObjectId.is_valid(bid)]
        if not valid_book_ids:
            return jsonify({"error": "No valid book IDs provided"}), 400

        # Capture deletion time (UTC)
        deletion_time = datetime.now(timezone.utc)

        # Fetch book details and uploader information
        book_details_list = []
        uploader_ids = set()
        for book_id in valid_book_ids:
            book_detail = book_model.get_book_details_for_email(mongo, book_id, deletion_time)
            if book_detail:
                book_details_list.append(book_detail)
                book = mongo.db.books.find_one({"_id": ObjectId(book_id)})
                if book and book.get("createdBy"):
                    uploader_ids.add(str(book.get("createdBy")))

        if not book_details_list:
            return jsonify({"error": "No valid books found"}), 404

        # Get deleter details
        deleter_id = get_jwt_identity()
        deleter = User.find_by_id(deleter_id)
        if not deleter:
            return jsonify({"error": "Deleter not found"}), 404

        # Get admin(s)
        admins = mongo.db.users.find({"role": UserRoles.ADMIN})
        admin_list = [{"fullName": admin.get("fullName", "Unknown"), "email": admin.get("email", ""), "role": admin.get("role", "admin")} for admin in admins]

        # Determine recipients
        recipients = admin_list
        for uploader_id in uploader_ids:
            uploader = User.find_by_id(uploader_id)
            if uploader:
                recipients.append({
                    "fullName": uploader.get("fullName", "Unknown"),
                    "email": uploader.get("email", ""),
                    "role": uploader.get("role", "book_manager")
                })
        if str(deleter_id) not in uploader_ids:
            recipients.append({
                "fullName": deleter.get("fullName", "Unknown"),
                "email": deleter.get("email", ""),
                "role": deleter.get("role", "book_manager")
            })

        # Remove duplicates by email
        unique_recipients = {recipient["email"]: recipient for recipient in recipients if recipient["email"]}.values()

        # Delete books and associated OCR processes
        deleted_count = 0
        for book_id in valid_book_ids:
            ocr_model.update_ocr_process(mongo, book_id, {"status": "failed", "errorMessage": "Book deleted"})
            if book_model.delete_book(mongo, book_id):
                deleted_count += 1

        if deleted_count == 0:
            return jsonify({"error": "Failed to delete any books"}), 500

        # Send email notifications
        send_deletion_email(
            unique_recipients,
            book_details_list,
            deleter.get("fullName", "Unknown"),
            deleter.get("role", "book_manager"),
            deletion_time
        )

        return jsonify({"message": f"{deleted_count} book{'s' if deleted_count > 1 else ''} deleted successfully"}), 200

    except Exception as e:
        print(f"Error in delete_books: {str(e)}")
        return jsonify({"error": str(e)}), 500

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

        # Check if OCR process is completed before allowing public visibility
        if new_visibility == "public":
            ocr_process = ocr_model.get_ocr_process_by_book(mongo, book_id)
            if not ocr_process or ocr_process["status"] != "completed":
                return jsonify({"error": "Cannot set visibility to public until OCR process is completed"}), 400

        success = book_model.update_book(mongo, book_id, {"visibility": new_visibility})

        if success:
            return jsonify({"message": f"Book visibility updated to '{new_visibility}'"}), 200
        else:
            return jsonify({"error": "Failed to update visibility"}), 500

    except Exception as e:
        return jsonify({"error": str(e)}), 500