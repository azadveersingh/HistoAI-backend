from flask import Blueprint, request, jsonify, send_file
from flask_jwt_extended import jwt_required, get_jwt_identity
from werkzeug.utils import secure_filename
from bson import ObjectId
from datetime import datetime, timezone, timedelta
import os
import smtplib
from email.mime.text import MIMEText
from dotenv import load_dotenv
from ..models.user import User, UserRoles
from ..models import book_model, project_model, ocr_model, structured_data
from ..extensions import mongo, socketio
from ..helpers.auth_helpers import role_required
from ..helpers.file_helpers import allowed_file, create_pdf_preview, create_book_folder_structure
from ..config import Config
from .ocr_processor import process_book_ocr
from .chunking import process_and_get_chunks
from .data_extraction import send_chunks_to_llm
from PyPDF2 import PdfReader
import logging

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

# Load email config from .env
load_dotenv()
EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_PORT = int(os.getenv("EMAIL_PORT"))
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
local_LLM_URL = os.getenv("local_LLM_URL")
openai_LLM_URL = os.getenv("openai_LLM_URL")
X_API_KEY = os.getenv("X_API_KEY")
BASE_URL = os.getenv("BASE_URL")

book_bp = Blueprint("books", __name__, url_prefix="/api/books")

MAX_TOTAL_UPLOAD_MB = 150

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
        authors2 = request.form.getlist("author2")
        editions = request.form.getlist("edition")
        selected_llm_url = request.form.get("llm_url", local_LLM_URL)

        if len(book_names) != len(files) or len(authors) != len(files):
            return jsonify({"error": "Number of bookName and primary author entries must match number of files"}), 400

        user_id = get_jwt_identity()
        uploaded = []
        failed_uploads = []

        for i, file in enumerate(files):
            if not allowed_file(file.filename):
                socketio.emit("book_progress", {
                    "book_id": None,
                    "status": "error",
                    "message": f"Invalid file type for {file.filename}. Only PDF and DOCX are allowed."
                }, room=user_id)
                failed_uploads.append({
                    "fileName": file.filename,
                    "error": "Invalid file type. Only PDF and DOCX are allowed."
                })
                continue

            book_name = book_names[i].strip().upper()
            author = authors[i].strip().upper()
            author2 = authors2[i].strip().upper() if i < len(authors2) and authors2[i].strip() else ""
            edition = editions[i].strip().upper() if i < len(editions) else ""

            if not book_name or not author:
                socketio.emit("book_progress", {
                    "book_id": None,
                    "status": "error",
                    "message": f"bookName and primary author are required for file {file.filename}"
                }, room=user_id)
                failed_uploads.append({
                    "fileName": file.filename,
                    "error": f"bookName and primary author are required for file {file.filename}"
                })
                continue

            existing = mongo.db.books.find_one({"bookName": book_name})
            if existing:
                socketio.emit("book_progress", {
                    "book_id": None,
                    "status": "error",
                    "message": f"Book name '{book_name}' already exists"
                }, room=user_id)
                failed_uploads.append({
                    "fileName": file.filename,
                    "error": f"Book name '{book_name}' already exists"
                })
                continue

            book_doc = {
                "bookName": book_name,
                "author": author,
                "author2": author2,
                "edition": edition,
                "createdBy": ObjectId(user_id),
                "createdAt": datetime.now(timezone.utc),
                "updatedAt": datetime.now(timezone.utc)
            }
            inserted_id = book_model.create_book(mongo, book_doc)

            socketio.emit("book_progress", {
                "book_id": inserted_id,
                "status": "book_received",
                "message": f"Book '{book_name}' received for processing"
            }, room=user_id)

            book_dir = create_book_folder_structure(inserted_id)
            filename = secure_filename(file.filename)
            filepath = os.path.join(book_dir, filename)
            file.save(filepath)

            file_size = os.path.getsize(filepath)
            pdf_file_path = f"{inserted_id}/{filename}"  # previewUrl points to the PDF file

            try:
                with open(filepath, "rb") as f:
                    reader = PdfReader(f)
                    pages = len(reader.pages)
                socketio.emit("book_progress", {
                    "book_id": inserted_id,
                    "status": "total_pages",
                    "message": f"Book '{book_name}' has {pages} pages",
                    "total_pages": pages
                }, room=user_id)
            except Exception as e:
                pages = 0
                socketio.emit("book_progress", {
                    "book_id": inserted_id,
                    "status": "error",
                    "message": f"Failed to read pages for {filename}: {str(e)}"
                }, room=user_id)
                failed_uploads.append({
                    "fileName": filename,
                    "error": f"Failed to read pages: {str(e)}"
                })
                continue

            try:
                preview_image_path = create_pdf_preview(inserted_id, filepath)  # JPG preview image path
            except Exception as e:
                socketio.emit("book_progress", {
                    "book_id": inserted_id,
                    "status": "error",
                    "message": f"Failed to create preview for {filename}: {str(e)}"
                }, room=user_id)
                failed_uploads.append({
                    "fileName": filename,
                    "error": f"Failed to create preview: {str(e)}"
                })
                continue

            ocr_process_id = ocr_model.create_ocr_process(mongo, inserted_id)
            book_model.update_book(mongo, inserted_id, {"ocrProcessId": ObjectId(ocr_process_id)})

            socketio.emit("book_progress", {
                "book_id": inserted_id,
                "status": "start_ocr_processing",
                "message": f"Starting OCR processing for '{book_name}'"
            }, room=user_id)
            success, message = process_book_ocr(inserted_id, filepath)
            if not success:
                socketio.emit("book_progress", {
                    "book_id": inserted_id,
                    "status": "error",
                    "message": f"OCR failed for '{book_name}': {message}"
                }, room=user_id)
                failed_uploads.append({
                    "fileName": filename,
                    "error": message
                })
                book_model.update_book(mongo, inserted_id, {
                    "fileName": filename,
                    "fileSize": file_size,
                    "pages": pages,
                    "visibility": "public",
                    "frontPageImagePath": preview_image_path,
                    "previewUrl": pdf_file_path,  # Explicitly set to PDF path
                    "ocrProcessId": ObjectId(ocr_process_id),
                    "ocrStatus": "failed"
                })
                continue

            socketio.emit("book_progress", {
                "book_id": inserted_id,
                "status": "ocr_done",
                "message": f"OCR completed for '{book_name}'"
            }, room=user_id)

            try:
                chunk_results, csv_file_path = process_and_get_chunks(filepath, book_dir, filename, inserted_id)
                if not chunk_results:
                    socketio.emit("book_progress", {
                        "book_id": inserted_id,
                        "status": "error",
                        "message": f"Chunking failed for '{book_name}'"
                    }, room=user_id)
                    failed_uploads.append({
                        "fileName": filename,
                        "error": "Chunking failed"
                    })
                    book_model.update_book(mongo, inserted_id, {
                        "fileName": filename,
                        "fileSize": file_size,
                        "pages": pages,
                        "visibility": "public",
                        "frontPageImagePath": preview_image_path,
                        "previewUrl": pdf_file_path,  # Explicitly set to PDF path
                        "ocrProcessId": ObjectId(ocr_process_id),
                        "ocrStatus": "failed",
                        "chunkCsvPath": ""
                    })
                    continue
            except Exception as e:
                socketio.emit("book_progress", {
                    "book_id": inserted_id,
                    "status": "error",
                    "message": f"Chunking failed for '{book_name}': {str(e)}"
                }, room=user_id)
                failed_uploads.append({
                    "fileName": filename,
                    "error": f"Chunking failed: {str(e)}"
                })
                book_model.update_book(mongo, inserted_id, {
                    "fileName": filename,
                    "fileSize": file_size,
                    "pages": pages,
                    "visibility": "public",
                    "frontPageImagePath": preview_image_path,
                    "previewUrl": pdf_file_path,  # Explicitly set to PDF path
                    "ocrProcessId": ObjectId(ocr_process_id),
                    "ocrStatus": "failed",
                    "chunkCsvPath": ""
                })
                continue

            try:
                result, status_code = send_chunks_to_llm(
                    inserted_id, csv_file_path, book_dir, book_name, user_id,
                    filename, pdf_file_path, filepath, inserted_id, selected_llm_url
                )
                if status_code != 200:
                    socketio.emit("book_progress", {
                        "book_id": inserted_id,
                        "status": "error",
                        "message": f"Structured data extraction failed for '{book_name}': {result.get('error', 'Unknown error')}"
                    }, room=user_id)
                    failed_uploads.append({
                        "fileName": filename,
                        "error": result.get("error", "Structured data processing failed")
                    })
                    book_model.update_book(mongo, inserted_id, {
                        "fileName": filename,
                        "fileSize": file_size,
                        "pages": pages,
                        "visibility": "public",
                        "frontPageImagePath": preview_image_path,
                        "previewUrl": pdf_file_path,  # Explicitly set to PDF path
                        "ocrProcessId": ObjectId(ocr_process_id),
                        "ocrStatus": "completed",
                        "chunkCsvPath": csv_file_path
                    })
                    continue
            except Exception as e:
                socketio.emit("book_progress", {
                    "book_id": inserted_id,
                    "status": "error",
                    "message": f"Structured data extraction failed for '{book_name}': {str(e)}"
                }, room=user_id)
                failed_uploads.append({
                    "fileName": filename,
                    "error": f"Structured data extraction failed: {str(e)}"
                })
                book_model.update_book(mongo, inserted_id, {
                    "fileName": filename,
                    "fileSize": file_size,
                    "pages": pages,
                    "visibility": "public",
                    "frontPageImagePath": preview_image_path,
                    "previewUrl": pdf_file_path,  # Explicitly set to PDF path
                    "ocrProcessId": ObjectId(ocr_process_id),
                    "ocrStatus": "completed",
                    "chunkCsvPath": csv_file_path
                })
                continue

            socketio.emit("book_progress", {
                "book_id": inserted_id,
                "status": "book_processing_complete",
                "message": f"Book processing completed for '{book_name}'"
            }, room=user_id)

            book_doc_update = {
                "fileName": filename,
                "fileSize": file_size,
                "pages": pages,
                "visibility": "public",
                "frontPageImagePath": preview_image_path,  # JPG preview image
                "previewUrl": pdf_file_path,  # PDF file path
                "ocrProcessId": ObjectId(ocr_process_id),
                "ocrStatus": "completed",
                "chunkCsvPath": csv_file_path
            }
            book_model.update_book(mongo, inserted_id, book_doc_update)

            uploaded.append({
                "bookId": inserted_id,
                "fileName": filename,
                "bookName": book_name,
                "author": author,
                "author2": author2,
                "edition": edition,
                "pages": pages,
                "previewUrl": f"/{pdf_file_path}",  # Return PDF path
                "ocrStatus": "completed",
                "ocrMessage": message,
                "chunkCsvPath": csv_file_path,
                "frontPageImagePath": f"/{preview_image_path}"  # Return JPG preview path
            })

        if not uploaded and failed_uploads:
            return jsonify({
                "error": "All uploads failed",
                "failed": failed_uploads
            }), 400

        return jsonify({
            "message": "Books uploaded, OCR processes started, chunks saved, and structured data extracted",
            "files": uploaded,
            "failed": failed_uploads
        }), 201

    except Exception as e:
        logger.error(f"Error in upload_books: {str(e)}")
        socketio.emit("book_progress", {
            "book_id": None,
            "status": "error",
            "message": f"Upload failed: {str(e)}"
        }, room=user_id)
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

        if "bookName" in data and data["bookName"].strip():
            book_name = data["bookName"].strip().upper()
            existing = mongo.db.books.find_one({"bookName": book_name, "_id": {"$ne": ObjectId(book_id)}})
            if existing:
                return jsonify({"error": f"Book name '{book_name}' already exists"}), 409
            update_fields["bookName"] = book_name

        if "author" in data:
            if not data["author"].strip():
                return jsonify({"error": "Primary author cannot be empty"}), 400
            update_fields["author"] = data["author"].strip().upper()

        if "author2" in data:
            update_fields["author2"] = data["author2"].strip().upper() if data["author2"].strip() else ""

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
        logger.error(f"Error in update_book_details for book_id {book_id}: {str(e)}")
        return jsonify({"error": f"Failed to update book details: {str(e)}"}), 500

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

        # Do not automatically set visibility to public; wait for explicit visibility update
        return jsonify({"message": "OCR process completed"}), 200

    except Exception as e:
        logger.error(f"Error in complete_ocr_process for book_id {book_id}: {str(e)}")
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

        # Validate that books have completed OCR and structured data processing
        valid_book_ids = []
        for bid in book_ids:
            if not ObjectId.is_valid(bid):
                continue
            ocr_process = ocr_model.get_ocr_process_by_book(mongo, bid)
            structured_data_process = structured_data.StructuredData.get_by_book(mongo, bid)
            if (ocr_process and ocr_process["status"] == "completed" and
                structured_data_process and structured_data_process["status"] == "completed"):
                valid_book_ids.append(ObjectId(bid))

        if not valid_book_ids:
            return jsonify({"error": "No books with completed OCR and structured data provided"}), 400

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
        logger.error(f"Error in add_books_to_project for project_id {project_id}: {str(e)}")
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
        logger.error(f"Error in remove_books_from_project for project_id {project_id}: {str(e)}")
        return jsonify({"error": str(e)}), 500

@book_bp.route("/", methods=["GET"])
@jwt_required()
@role_required([UserRoles.ADMIN, UserRoles.BM, UserRoles.PM, UserRoles.USER])
def get_all_books():
    try:
        # Only return books with completed OCR and structured data
        ocr_processes = mongo.db["ocr_process"].find({"status": "completed"})
        completed_ocr_book_ids = [str(ocr_process["bookId"]) for ocr_process in ocr_processes]
        structured_data_processes = mongo.db["structured_data"].find({"status": "completed"})
        completed_structured_data_book_ids = [str(process["bookId"]) for process in structured_data_processes]
        # Intersection of books with both OCR and structured data completed
        valid_book_ids = set(completed_ocr_book_ids) & set(completed_structured_data_book_ids)
        books = mongo.db["books"].find({"_id": {"$in": [ObjectId(bid) for bid in valid_book_ids]}})
        return jsonify({"books": [book_model.serialize_book(book) for book in books]}), 200
    except Exception as e:
        logger.error(f"Error in get_all_books: {str(e)}")
        return jsonify({"error": str(e)}), 500

@book_bp.route("/processing", methods=["GET"])
@jwt_required()
@role_required([UserRoles.BM])
def get_processing_books():
    try:
        ocr_processes = ocr_model.get_all_ocr_processes(mongo)
        structured_data_processes = structured_data.StructuredData.get_all(mongo)
        processing_books = []
        for ocr_process in ocr_processes:
            if ocr_process["status"] != "completed":
                book = book_model.get_book_by_id(mongo, ocr_process["bookId"])
                if book:
                    book["ocrStatus"] = ocr_process["status"]
                    book["progress"] = ocr_process["progress"]
                    book["errorMessage"] = ocr_process.get("errorMessage")
                    processing_books.append(book)
        for structured_data_process in structured_data_processes:
            if structured_data_process["status"] != "completed":
                book = book_model.get_book_by_id(mongo, structured_data_process["bookId"])
                if book:
                    book["structuredDataStatus"] = structured_data_process["status"]
                    book["structuredDataProgress"] = (structured_data_process["processedChunks"] / 
                                                    structured_data_process["totalChunks"] * 100 
                                                    if structured_data_process["totalChunks"] > 0 else 0)
                    book["structuredDataErrorMessage"] = structured_data_process.get("errorMessage")
                    processing_books.append(book)
        return jsonify({"books": processing_books}), 200
    except Exception as e:
        logger.error(f"Error in get_processing_books: {str(e)}")
        return jsonify({"error": f"Failed to fetch processing books: {str(e)}"}), 500

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
        logger.error(f"Error in get_project_books for project_id {project_id}: {str(e)}")
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
        logger.error(f"Error in get_projects_for_book for book_id {book_id}: {str(e)}")
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

        # Delete book (includes structured data deletion via book_model.delete_book)
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
        logger.error(f"Error in delete_book for book_id {book_id}: {str(e)}")
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
        logger.error(f"Error in delete_books: {str(e)}")
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

        if new_visibility == "public":
            ocr_process = ocr_model.get_ocr_process_by_book(mongo, book_id)
            if not ocr_process or ocr_process["status"] != "completed":
                return jsonify({"error": "Cannot set visibility to public until OCR process is completed"}), 400
            structured_data_process = structured_data.StructuredData.get_by_book(mongo, book_id)
            if not structured_data_process or structured_data_process["status"] != "completed":
                return jsonify({"error": "Cannot set visibility to public until structured data processing is completed"}), 400

        success = book_model.update_book(mongo, book_id, {"visibility": new_visibility})

        if success:
            return jsonify({"message": f"Book visibility updated to '{new_visibility}'"}), 200
        else:
            return jsonify({"error": "Failed to update visibility"}), 500
    except Exception as e:
        logger.error(f"Error in update_book_visibility for book_id {book_id}: {str(e)}")
        return jsonify({"error": f"Failed to update visibility: {str(e)}"}), 500

@book_bp.route("/<book_id>/ocr/text", methods=["GET"])
@jwt_required()
@role_required([UserRoles.ADMIN, UserRoles.BM, UserRoles.PM, UserRoles.USER])
def download_ocr_text(book_id):
    try:
        if not ObjectId.is_valid(book_id):
            return jsonify({"error": "Invalid book ID"}), 400

        ocr_process = ocr_model.get_ocr_process_by_book(mongo, book_id)
        if not ocr_process:
            return jsonify({"error": "OCR process not found for this book"}), 404

        if ocr_process["status"] != "completed":
            return jsonify({"error": "OCR process is not completed"}), 400

        text_file_path = ocr_process.get("ocrTextFilePath")
        if not text_file_path or not os.path.exists(text_file_path):
            return jsonify({"error": "OCR text file not found"}), 404

        # Redirect to the file serving route
        filename = os.path.join(book_id, "OCR_OUTPUT.TXT")
        return send_file(
            text_file_path,
            as_attachment=True,
            download_name=f"{book_id}_OCR.txt",
            mimetype="text/plain"
        )
    except Exception as e:
        logger.error(f"Error in download_ocr_text for book_id {book_id}: {str(e)}")
        return jsonify({"error": f"Failed to download OCR text: {str(e)}"}), 500

@book_bp.route("/<book_id>/structured-data", methods=["GET"])
@jwt_required()
@role_required([UserRoles.ADMIN, UserRoles.BM, UserRoles.PM, UserRoles.USER])
def download_structured_data(book_id):
    try:
        if not ObjectId.is_valid(book_id):
            return jsonify({"error": "Invalid book ID"}), 400

        structured_data_process = structured_data.StructuredData.get_by_book(mongo, book_id)
        if not structured_data_process:
            return jsonify({"error": "Structured data process not found for this book"}), 404

        if structured_data_process["status"] != "completed":
            return jsonify({"error": "Structured data processing is not completed"}), 400

        structured_data_path = structured_data_process.get("structuredDataPath")
        if not structured_data_path or not os.path.exists(structured_data_path):
            return jsonify({"error": "Structured data file not found"}), 404

        # Redirect to the file serving route
        filename = os.path.basename(structured_data_path)
        return send_file(
            structured_data_path,
            as_attachment=True,
            download_name=f"{book_id}_structured.json",
            mimetype="application/json"
        )
    except Exception as e:
        logger.error(f"Error in download_structured_data for book_id {book_id}: {str(e)}")
        return jsonify({"error": f"Failed to download structured data: {str(e)}"}), 500