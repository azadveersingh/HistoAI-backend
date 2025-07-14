import os
import shutil
from flask import current_app
# from bson import ObjectId
from ..extensions import mongo
# from ..helpers.file_helpers import create_pdf_preview

def rename_book(mongo, book_id, new_name, user_id):
    """Renames a book's folder and associated files, updates the database."""
    book = mongo.db.uploads.find_one({"_id":(book_id), "user_id": user_id})
    
    if not book:
        return {"error": "Book not found"}, 404

    old_folder_name = book["folder_name"]
    old_filename = book["filename"]
    upload_folder = current_app.config["UPLOAD_FOLDER"]

    # Construct paths
    old_folder_path = os.path.join(upload_folder, old_folder_name)
    new_folder_name = new_name.replace(" ", "_") + "$@$" + old_folder_name.split("$@$")[1]
    new_folder_path = os.path.join(upload_folder, new_folder_name)

    if os.path.exists(old_folder_path):
        os.rename(old_folder_path, new_folder_path)  # Rename folder
        
        old_file_base = os.path.splitext(old_filename)[0]

        # Rename files inside the folder
        old_pdf_path = os.path.join(new_folder_path, old_filename)
        new_pdf_path = os.path.join(new_folder_path, f"{new_name}.pdf")
        if os.path.exists(old_pdf_path):
            os.rename(old_pdf_path, new_pdf_path)

        old_csv_path = os.path.join(new_folder_path, f"{os.path.splitext(old_filename)[0]}.csv")
        new_csv_path = os.path.join(new_folder_path, f"{new_name}.csv")
        if os.path.exists(old_csv_path):
            os.rename(old_csv_path, new_csv_path)

        old_json_path = os.path.join(new_folder_path, f"{os.path.splitext(old_filename)[0]}_structured.json")
        new_json_path = os.path.join(new_folder_path, f"{new_name}_structured.json")
        if os.path.exists(old_json_path):
            os.rename(old_json_path, new_json_path)
            
        old_jpg_path = os.path.join(new_folder_path, f"{old_file_base}.jpg")
        new_jpg_path = os.path.join(new_folder_path, f"{new_name}.jpg")
        if os.path.exists(old_jpg_path):
            os.rename(old_jpg_path, new_jpg_path)
            print(f"✅ Preview image renamed: {new_jpg_path}")
        else:
            print(f"⚠️ No preview image found at: {old_jpg_path}")

        # Update MongoDB record
        mongo.db.uploads.update_one(
            {"_id": (book_id)},
            {"$set": {
                "filename": f"{new_name}.pdf",
                "folder_name": new_folder_name,
                "fileUrl": f"{new_folder_name}/{new_name}.pdf",
                "structured_data_path": f"{new_folder_name}/{new_name}_structured.json",
                "preview_url": f"{new_folder_name}/{new_name}.jpg"
            }}
        )

        return {"message": "Book renamed successfully", "book_id": book_id}, 200

    return {"error": "Folder not found"}, 500


def delete_book(mongo, book_id, user_id):
    """Deletes a book's folder and associated database record."""
    book = mongo.db.uploads.find_one({"_id":(book_id), "user_id": user_id})
    
    if not book:
        return {"error": "Book not found"}, 404

    folder_path = os.path.join(current_app.config["UPLOAD_FOLDER"], book["folder_name"])

    try:
        # Delete folder and contents
        if os.path.exists(folder_path):
            shutil.rmtree(folder_path)  

        # Remove entry from MongoDB
        mongo.db.uploads.delete_one({"_id":(book_id)})

        return {"message": "Book deleted successfully", "book_id": book_id}, 200

    except Exception as e:
        print(f"Error deleting book: {e}")
        return {"error": "Failed to delete book"}, 500
