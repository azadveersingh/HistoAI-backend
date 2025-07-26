from bson import ObjectId
from datetime import datetime, timezone
from ..models.user import User

BOOK_COLLECTION = "books"
PROJECT_COLLECTION = "project-details"
OCR_PROCESS_COLLECTION = "ocr_process"

def serialize_book(book):
    return {
        "_id": str(book["_id"]),
        "fileName": book.get("fileName"),
        "bookName": book.get("bookName"),
        "author": book.get("author"),
        "author2": book.get("author2", ""),  # Default to empty string if not present
        "edition": book.get("edition"),
        "fileSize": book.get("fileSize"),
        "pages": book.get("pages"),
        "visibility": book.get("visibility", "private"),
        "frontPageImagePath": book.get("frontPageImagePath"),
        "previewUrl": book.get("previewUrl"),
        "ocrProcessId": str(book["ocrProcessId"]) if book.get("ocrProcessId") else None,
        "createdBy": str(book["createdBy"]) if book.get("createdBy") else None,
        "createdAt": book.get("createdAt", datetime.now(timezone.utc)).isoformat(),
        "updatedAt": book.get("updatedAt", datetime.now(timezone.utc)).isoformat()
    }

def create_book(mongo, book_data):
    result = mongo.db[BOOK_COLLECTION].insert_one(book_data)
    return str(result.inserted_id)

def get_all_books(mongo):
    # Only return books with completed OCR processes
    ocr_processes = mongo.db[OCR_PROCESS_COLLECTION].find({"status": "completed"})
    completed_book_ids = [ocr_process["bookId"] for ocr_process in ocr_processes]
    books = mongo.db[BOOK_COLLECTION].find({"_id": {"$in": completed_book_ids}})
    return [serialize_book(book) for book in books]

def get_book_by_id(mongo, book_id):
    book = mongo.db[BOOK_COLLECTION].find_one({"_id": ObjectId(book_id)})
    if not book:
        return None
    return serialize_book(book)

def get_books_by_project(mongo, project_id):
    project = mongo.db[PROJECT_COLLECTION].find_one({"_id": ObjectId(project_id)})
    if not project or not project.get("bookIds"):
        return []
    book_ids = [ObjectId(bid) for bid in project["bookIds"]]
    books = mongo.db[BOOK_COLLECTION].find({"_id": {"$in": book_ids}})
    return [serialize_book(book) for book in books]

def update_book(mongo, book_id, update_fields):
    update_fields["updatedAt"] = datetime.now(timezone.utc)
    result = mongo.db[BOOK_COLLECTION].update_one(
        {"_id": ObjectId(book_id)},
        {"$set": update_fields}
    )
    return result.modified_count > 0

def delete_book(mongo, book_id):
    result = mongo.db[BOOK_COLLECTION].delete_one({"_id": ObjectId(book_id)})
    return result.deleted_count > 0

def get_books_by_creator(mongo, user_id):
    books = mongo.db[BOOK_COLLECTION].find({"createdBy": ObjectId(user_id)})
    return [serialize_book(book) for book in books]

def get_book_details_for_email(mongo, book_id, deletion_time):
    book = mongo.db[BOOK_COLLECTION].find_one({"_id": ObjectId(book_id)})
    if not book:
        return None
    uploader_id = book.get("createdBy")
    uploader = User.find_by_id(uploader_id) if uploader_id else None
    return {
        "bookName": book.get("bookName", "Untitled"),
        "author": book.get("author", "Unknown"),
        "author2": book.get("author2", "N/A"),  # Default to "N/A" for email if not present
        "edition": book.get("edition", "N/A"),
        "uploaderName": uploader.get("fullName", "Unknown") if uploader else "Unknown",
        "deletionTime": deletion_time
    }