from flask import Blueprint, jsonify, request, send_file
from flask_jwt_extended import jwt_required, get_jwt_identity
import os
import json
import pandas as pd
import io
from bson import ObjectId
from ..extensions import mongo
from ..models import book_model, project_model, collection_model, structured_data_model
from ..models.user import User, UserRoles
from ..helpers.auth_helpers import role_required
import logging
import xlsxwriter
from dotenv import load_dotenv

load_dotenv()
API_BASE_URL = os.getenv("BASE_URL")
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Uploads"))

logger = logging.getLogger(__name__)

structured_bp = Blueprint("structured", __name__, url_prefix="/api/structured")

def generate_excel_data(structured_data, book_name):
    """Generate structured data rows for Excel export."""
    extracted_rows = []
    sr_no = 1
    for entry in structured_data:
        source_url = entry.get("Source URL", "N/A")
        result_data = entry.get("Result", "")

        if not result_data or result_data.strip() == "":
            parsed_result = {}
        else:
            try:
                parsed_result = json.loads(result_data)
                if not isinstance(parsed_result, dict):
                    parsed_result = {}
            except json.JSONDecodeError:
                parsed_result = {}

        events = parsed_result.get("Events", [])
        if not isinstance(events, list):
            events = []

        if not events:
            row = {
                "Sr. No": sr_no,
                "Book Name": book_name,
                "Event Name": "N/A",
                "Description": "N/A",
                "Participants": "N/A",
                "Location": "N/A",
                "Place": "N/A",
                "Start Date": "N/A",
                "End Date": "N/A",
                "Key Details": "N/A",
                "Day": "N/A",
                "Month": "N/A",
                "Year": "N/A",
                "General Comments": "N/A",
                "Source URL": source_url
            }

            # Skip if all values (except Sr. No, Book Name, and Source URL) are N/A
            data_fields = [v for k, v in row.items() if k not in ["Sr. No", "Book Name", "Source URL"]]
            if all(val == "N/A" for val in data_fields):
                continue

            extracted_rows.append(row)
            sr_no += 1
        else:
            for event in events:
                if not isinstance(event, dict):
                    continue
                row = {
                    "Sr. No": sr_no,
                    "Book Name": book_name,
                    "Event Name": event.get("Event Name", "N/A"),
                    "Description": event.get("Description", "N/A"),
                    "Participants": ", ".join(str(p) for p in event.get("Participants/People", []) if p) if isinstance(event.get("Participants/People"), list) else "N/A",
                    "Location": event.get("Location", "N/A"),
                    "Place": event.get("Place", "N/A"),
                    "Start Date": event.get("Start Date", "N/A"),
                    "End Date": event.get("End Date", "N/A"),
                    "Key Details": event.get("Key Details", "N/A"),
                    "Day": event.get("Day", "N/A"),
                    "Month": event.get("Month", "N/A"),
                    "Year": event.get("Year", "N/A"),
                    "General Comments": event.get("General Comments", "N/A"),
                    "Source URL": source_url
                }

                # Skip if all values (except Sr. No, Book Name, and Source URL) are N/A
                data_fields = [v for k, v in row.items() if k not in ["Sr. No", "Book Name", "Source URL"]]
                if all(val == "N/A" for val in data_fields):
                    continue

                extracted_rows.append(row)
                sr_no += 1

    return extracted_rows

def create_excel_file(extracted_rows, filename):
    """Create an Excel file from extracted rows."""
    if not extracted_rows:
        return None, "No structured data to export"

    column_order = list(extracted_rows[0].keys())
    df = pd.DataFrame(extracted_rows)[column_order]

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Structured Data")
        workbook = writer.book
        worksheet = writer.sheets["Structured Data"]
        hyperlink_format = workbook.add_format({'font_color': 'blue', 'underline': 1})
        source_url_column_index = df.columns.get_loc("Source URL")
        for row_num, url in enumerate(df["Source URL"], start=0):
            if url and url != "N/A":
                full_url = f"{API_BASE_URL}/{url.lstrip('/')}"
                worksheet.write_url(row_num + 1, source_url_column_index, full_url, hyperlink_format, "Open PDF")

    output.seek(0)
    return output, f"{os.path.splitext(filename)[0]}_structured.xlsx"

@structured_bp.route("/book/<book_id>", methods=["GET"])
@jwt_required()
@role_required([UserRoles.ADMIN, UserRoles.BM, UserRoles.PM, UserRoles.USER])
def get_book_structured_data(book_id):
    try:
        if not ObjectId.is_valid(book_id):
            logger.error(f"Invalid ObjectId format for book_id: {book_id}")
            return jsonify({"error": "Invalid book ID format"}), 400

        user_id = get_jwt_identity()
        logger.info(f"Received request for structured data - Book ID: {book_id}, User ID: {user_id}")

        book = book_model.get_book_by_id(mongo, book_id)
        if not book:
            logger.error("Book not found in database")
            return jsonify({"error": "Book not found"}), 404

        # Check access: if private, only creator or admin
        if book["visibility"] == "private":
            if book["createdBy"] != user_id and User.find_by_id(user_id)["role"] != UserRoles.ADMIN:
                logger.error("Unauthorized access to private book")
                return jsonify({"error": "Unauthorized access to private book"}), 403

        structured_process = structured_data_model.StructuredData.get_by_book(mongo, book_id)
        if not structured_process or structured_process["status"] != "completed":
            logger.error("Structured data not available or not completed")
            return jsonify({"error": "Structured data not available or not completed"}), 404

        structured_path = structured_process["structuredDataPath"]
        if not os.path.exists(structured_path):
            logger.error(f"Structured data file not found at: {structured_path}")
            return jsonify({"error": "Structured data file not found"}), 404

        with open(structured_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info("Successfully loaded structured data")
        return jsonify({"data": data}), 200

    except Exception as e:
        logger.error(f"Error in get_book_structured_data: {str(e)}")
        return jsonify({"error": str(e)}), 500

@structured_bp.route("/book/<book_id>/export-excel", methods=["GET"])
@jwt_required()
@role_required([UserRoles.ADMIN, UserRoles.BM, UserRoles.PM, UserRoles.USER])
def export_book_excel(book_id):
    try:
        if not ObjectId.is_valid(book_id):
            logger.error(f"Invalid ObjectId format for book_id: {book_id}")
            return jsonify({"error": "Invalid book ID format"}), 400

        user_id = get_jwt_identity()
        logger.info(f"Received request for Excel export - Book ID: {book_id}, User ID: {user_id}")

        book = book_model.get_book_by_id(mongo, book_id)
        if not book:
            logger.error("Book not found in database")
            return jsonify({"error": "Book not found"}), 404

        # Check access: if private, only creator or admin
        if book["visibility"] == "private":
            if book["createdBy"] != user_id and User.find_by_id(user_id)["role"] != UserRoles.ADMIN:
                logger.error("Unauthorized access to private book")
                return jsonify({"error": "Unauthorized access to private book"}), 403

        # Fetch structured data path and filename from Uploads collection
        user_upload = mongo.db.Uploads.find_one(
            {"_id": ObjectId(book_id), "user_id": user_id},
            {"structured_data_path": 1, "filename": 1}
        )
        if not user_upload:
            logger.error("No structured data found in Uploads collection")
            return jsonify({"error": "No structured data found"}), 404

        structured_path = user_upload.get("structured_data_path")
        if not structured_path:
            logger.error("No structured data path in database")
            return jsonify({"error": "No structured data available"}), 404

        absolute_path = os.path.join(BASE_DIR, structured_path)
        if not os.path.exists(absolute_path):
            logger.error(f"Structured data file not found at: {absolute_path}")
            return jsonify({"error": "Structured data file not found"}), 404

        filename = user_upload.get("filename", book["bookName"])

        # Load JSON data
        with open(absolute_path, "r", encoding="utf-8") as json_file:
            structured_data = json.load(json_file)

        # Generate Excel data
        extracted_rows = generate_excel_data(structured_data, book.get("bookName", "N/A"))
        output, excel_filename = create_excel_file(extracted_rows, filename)
        if not output:
            logger.error(excel_filename)
            return jsonify({"error": excel_filename}), 400

        return send_file(
            output,
            as_attachment=True,
            download_name=excel_filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    except Exception as e:
        logger.error(f"Error in export_book_excel: {str(e)}")
        return jsonify({"error": str(e)}), 500

@structured_bp.route("/project/<project_id>", methods=["POST"])
@jwt_required()
@role_required([UserRoles.ADMIN, UserRoles.BM, UserRoles.PM, UserRoles.USER])
def get_project_structured_data(project_id):
    try:
        if not ObjectId.is_valid(project_id):
            logger.error(f"Invalid ObjectId format for project_id: {project_id}")
            return jsonify({"error": "Invalid project ID"}), 400

        user_id = ObjectId(get_jwt_identity())
        logger.info(f"Received request for project structured data - Project ID: {project_id}, User ID: {user_id}")

        project = project_model.get_project_by_id(mongo, project_id)
        if not project:
            logger.error("Project not found in database")
            return jsonify({"error": "Project not found"}), 404

        # Check if user is creator or member
        if str(project["createdBy"]) != str(user_id) and user_id not in [ObjectId(mid) for mid in project["memberIds"]]:
            logger.error("Unauthorized: Not a project member or creator")
            return jsonify({"error": "Unauthorized: Not a project member or creator"}), 403

        data = request.get_json()
        selected_collection_ids = data.get("collectionIds", [])
        selected_book_ids = data.get("bookIds", [])

        # Validate selected collections and books belong to the project
        project_collection_ids = [str(cid) for cid in project.get("collectionIds", [])]
        project_book_ids = [str(bid) for bid in project.get("bookIds", [])]

        valid_collection_ids = [cid for cid in selected_collection_ids if cid in project_collection_ids]
        valid_book_ids = [bid for bid in selected_book_ids if bid in project_book_ids]

        if len(valid_collection_ids) != len(selected_collection_ids) or len(valid_book_ids) != len(selected_book_ids):
            logger.error("Some selected collections or books do not belong to this project")
            return jsonify({"error": "Some selected collections or books do not belong to this project"}), 400

        # Gather all unique book IDs from selected books and collections
        all_book_ids = set(valid_book_ids)
        for cid in valid_collection_ids:
            collection = collection_model.get_collection_by_id(mongo, cid)
            if collection:
                all_book_ids.update(str(bid) for bid in collection.get("bookIds", []))

        # Fetch structured data for selected books only
        combined_data = []
        for book_id in all_book_ids:
            book = book_model.get_book_by_id(mongo, book_id)
            if not book or book["visibility"] != "public":
                continue

            structured_process = structured_data_model.StructuredData.get_by_book(mongo, book_id)
            if not structured_process or structured_process["status"] != "completed":
                continue

            structured_path = structured_process["structuredDataPath"]
            if not os.path.exists(structured_path):
                continue

            with open(structured_path, "r", encoding="utf-8") as f:
                book_data = json.load(f)
                if isinstance(book_data, list):
                    combined_data.extend(book_data)

        if not combined_data:
            logger.error("No structured data available for selected books and collections")
            return jsonify({"error": "No structured data available for selected books and collections"}), 404

        logger.info("Successfully loaded project structured data")
        return jsonify({"data": combined_data}), 200

    except Exception as e:
        logger.error(f"Error in get_project_structured_data: {str(e)}")
        return jsonify({"error": str(e)}), 500

@structured_bp.route("/project/<project_id>/export-excel", methods=["POST"])
@jwt_required()
@role_required([UserRoles.ADMIN, UserRoles.BM, UserRoles.PM, UserRoles.USER])
def export_project_excel(project_id):
    try:
        if not ObjectId.is_valid(project_id):
            logger.error(f"Invalid ObjectId format for project_id: {project_id}")
            return jsonify({"error": "Invalid project ID"}), 400

        user_id = ObjectId(get_jwt_identity())
        logger.info(f"Received request for project Excel export - Project ID: {project_id}, User ID: {user_id}")

        project = project_model.get_project_by_id(mongo, project_id)
        if not project:
            logger.error("Project not found in database")
            return jsonify({"error": "Project not found"}), 404

        # Check if user is creator or member
        if str(project["createdBy"]) != str(user_id) and user_id not in [ObjectId(mid) for mid in project["memberIds"]]:
            logger.error("Unauthorized: Not a project member or creator")
            return jsonify({"error": "Unauthorized: Not a project member or creator"}), 403

        data = request.get_json()
        selected_collection_ids = data.get("collectionIds", [])
        selected_book_ids = data.get("bookIds", [])

        # Validate selected collections and books
        project_collection_ids = [str(cid) for cid in project.get("collectionIds", [])]
        project_book_ids = [str(bid) for bid in project.get("bookIds", [])]

        valid_collection_ids = [cid for cid in selected_collection_ids if cid in project_collection_ids]
        valid_book_ids = [bid for bid in selected_book_ids if bid in project_book_ids]

        if len(valid_collection_ids) != len(selected_collection_ids) or len(valid_book_ids) != len(selected_book_ids):
            logger.error("Some selected collections or books do not belong to this project")
            return jsonify({"error": "Some selected collections or books do not belong to this project"}), 400

        # Gather all unique book IDs from selected books and collections
        all_book_ids = set(valid_book_ids)
        for cid in valid_collection_ids:
            collection = collection_model.get_collection_by_id(mongo, cid)
            if collection:
                all_book_ids.update(str(bid) for bid in collection.get("bookIds", []))

        # Fetch structured data for selected books only
        extracted_rows = []
        for book_id in all_book_ids:
            book = book_model.get_book_by_id(mongo, book_id)
            if not book or book["visibility"] != "public":
                continue

            # Fetch structured data path from Uploads collection
            user_upload = mongo.db.Uploads.find_one(
                {"_id": ObjectId(book_id)},
                {"structured_data_path": 1}
            )
            if not user_upload or not user_upload.get("structured_data_path"):
                continue

            structured_path = user_upload["structured_data_path"]
            absolute_path = os.path.join(BASE_DIR, structured_path)
            if not os.path.exists(absolute_path):
                continue

            with open(absolute_path, "r", encoding="utf-8") as json_file:
                structured_data = json.load(json_file)

            # Generate Excel data for this book
            book_rows = generate_excel_data(structured_data, book.get("bookName", "N/A"))
            extracted_rows.extend(book_rows)

        output, excel_filename = create_excel_file(extracted_rows, project["name"])
        if not output:
            logger.error(excel_filename)
            return jsonify({"error": excel_filename}), 400

        return send_file(
            output,
            as_attachment=True,
            download_name=excel_filename,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    except Exception as e:
        logger.error(f"Error in export_project_excel: {str(e)}")
        return jsonify({"error": str(e)}), 500