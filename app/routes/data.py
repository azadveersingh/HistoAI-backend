from flask import Blueprint, jsonify, send_file, request
from flask_jwt_extended import jwt_required, get_jwt_identity
import os
import json
import pandas as pd
import io
from bson import ObjectId 
from ..extensions import mongo
from urllib.parse import quote
import xlsxwriter
import urllib.parse 
from dotenv import load_dotenv

from flask_cors import CORS 

bp = Blueprint("excel_data", __name__, url_prefix="/api")

load_dotenv()

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..","uploads"))
API_BASE_URL = os.getenv("BASE_URL")
print("API_BASE_URL", API_BASE_URL)


@bp.route("/excel-data/<book_id>", methods=["GET"])
@jwt_required()
def get_excel_data(book_id):
    user_id = get_jwt_identity()
    print(f"Received request for Book ID: {book_id}, User ID: {user_id}")

    try: 
        book_object_id =(book_id) 
    except Exception as e:
        print("❌ Invalid ObjectId format:", e)
        return jsonify({"error": "Invalid book ID format"}), 400
    print("book object id", book_object_id)
    
    user_upload = mongo.db.uploads.find_one(
        {"_id": book_object_id, "user_id": user_id},
        {"_id": 0, "structured_data_path": 1, "fileUrl": 1}
    )

    print("MongoDB Query Result:", user_upload)

    if not user_upload:
        print("❌ Book not found in database!")
        return jsonify({"error": "Book not found"}), 404

    structured_data_path = user_upload.get("structured_data_path")
    fileUrl = user_upload.get("fileUrl")
    print("fileUrl", fileUrl)
    
    if not structured_data_path:
        print("❌ No structured data path in database!")
        return jsonify({"error": "No structured data available"}), 404
    
    absolute_path = os.path.join(BASE_DIR, structured_data_path)
    
    if not fileUrl:
        print("❌ No fileUrl in database!")
        return jsonify({"error": "No fileUrl available"}), 404

    try:
        with open(absolute_path, "r", encoding="utf-8") as json_file:
            structured_data = json.load(json_file)
        print("✅ Successfully loaded structured data!")
        return jsonify({"data": structured_data}), 200
    except FileNotFoundError:
        print("❌ Structured data file not found at:", absolute_path)
        return jsonify({"error": "Structured data file not found"}), 404
    except json.JSONDecodeError:
        print("❌ Error decoding JSON data!")
        return jsonify({"error": "Error decoding structured data"}), 500

# ---------------------------------------------Excel Download API-----------------------------------------------
@bp.route("/export-excel", methods=["GET"])
@jwt_required()
def export_excel():
    user_id = get_jwt_identity()
    book_id = request.args.get("bookId")
    print(f"Received request for Book ID: {book_id}")

    if not book_id:
        return jsonify({"error": "Book ID is required"}), 400
    
    try:
        book_object_id =(book_id)  
    except Exception as e:
        print("❌ Invalid ObjectId format:", e)
        return jsonify({"error": "Invalid book ID format"}), 400
    
    user_upload = mongo.db.uploads.find_one(
        {"user_id": user_id, "_id": book_object_id}, 
        {"structured_data_path": 1, "filename": 1}
    )
    if not user_upload:
        return jsonify({"error": "No structured data found"}), 404

    structured_data_path = user_upload.get("structured_data_path")
    original_filename = user_upload.get("filename", "structured_data")

    absolute_path = os.path.join(BASE_DIR, structured_data_path)
    print("Absolute Path for export excel:", absolute_path)

    if not structured_data_path or not os.path.exists(absolute_path):
        return jsonify({"error": "Structured data file not found"}), 404

    # Load JSON data from the structured data file
    with open(absolute_path, "r", encoding="utf-8") as json_file:
        structured_data = json.load(json_file)

    # Process data into a structured format
    extracted_rows = []
    sr_no = 1
    
    for entry in structured_data:
        sr_no = 1
        source_url = entry.get("Source URL")
        result_data = entry.get("Result")
        
        if not result_data or result_data.strip() == "":
            parsed_result = {}
        else:
            try:
                parsed_result = json.loads(result_data)
                if not isinstance(parsed_result, dict):  
                    parsed_result = {}
            except json.JSONDecodeError:
                parsed_result = {}
        events = parsed_result.get("Events")
        if not isinstance(events, list):
            events = []

        if not events:
            row = {
                # "Sr. No": sr_no,
                "Event Name": "N/A",
                "Description": "N/A",
                "Participants/People": "N/A",
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

            # Skip if all values (except Sr. No and Source URL) are N/A
            data_fields = [v for k, v in row.items() if k not in ["Sr. No", "Source URL"]]
            if all(val == "N/A" for val in data_fields):
                continue

            extracted_rows.append(row)
            sr_no += 1
        else:
            for event in events:
                if not isinstance(event, dict):
                    continue
                row = {
                    # "Sr. No": sr_no,
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

                # Check if all fields except Sr. No and Source URL are N/A
                data_fields = [v for k, v in row.items() if k not in ["Sr. No", "Source URL"]]
                if all(val == "N/A" for val in data_fields):
                    continue  # Skip this row

                extracted_rows.append(row)
                sr_no += 1


    if not extracted_rows:
        return jsonify({"error": "No structured data to export"}), 400

    
    column_order = list(extracted_rows[0].keys())

 
    df = pd.DataFrame(extracted_rows)[column_order]

    
    output = io.BytesIO()
    df["Source URL"]
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Structured Data")
         # Apply formatting for hyperlinks
        workbook = writer.book
        worksheet = writer.sheets["Structured Data"]
        hyperlink_format = workbook.add_format({'font_color': 'blue', 'underline': 1})
        source_url_column_index = df.columns.get_loc("Source URL")
        for row_num, url in enumerate(df["Source URL"], start=0):
            if url and url != "N/A":
                # Prepend the API base URL
                full_url = f"{API_BASE_URL}/{url}"
                
                # Write clickable link to Excel
                worksheet.write_url(row_num + 1, source_url_column_index, full_url, hyperlink_format, "Open PDF")

    output.seek(0)

    # Extract filename without extension and append .xlsx
    excel_filename = f"{os.path.splitext(original_filename)[0]}.xlsx"

    return send_file(output, as_attachment=True, download_name=excel_filename)
@bp.route("/users", methods=["GET"])
def get_users():
    try:
        users_collection = mongo.db.users  
        users = list(users_collection.find({}, {"_id": 1, "name": 1, "email": 1, "role": 1}))
        for user in users:
            user["_id"] = str(user["_id"])
        return jsonify(users), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route("/uploads", methods=["GET"])
def get_uploads():
    try:
        uploads_collection = mongo.db.uploads
        users_collection = mongo.db.users

        uploads = list(uploads_collection.find({}, {
            "_id": 1, "filename": 1, "folder_name": 1, "upload_time": 1, "file_size": 1, "user_id": 1
        }))

        for upload in uploads:
            upload["_id"] = str(upload["_id"])
            upload["user_id"] = str(upload["user_id"])

            
            user = users_collection.find_one({"_id": ObjectId(upload["user_id"])}, {"name": 1, "email": 1})
            upload["uploaded_by"] = user["name"] if user else "Unknown"
            upload["uploader_email"] = user["email"] if user else "Unknown"

        return jsonify(uploads), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@bp.route("/users/<user_id>", methods=["DELETE"])
def delete_user(user_id):
    try:
        users_collection = mongo.db.users
        result = users_collection.delete_one({"_id": ObjectId(user_id)})
        if result.deleted_count == 0:
            return jsonify({"error": "User not found"}), 404
        return jsonify({"message": "User deleted successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500