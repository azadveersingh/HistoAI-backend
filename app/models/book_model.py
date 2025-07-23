from bson import ObjectId
from datetime import datetime, timezone

BOOK_COLLECTION = "books"
PROJECT_COLLECTION = "project-details"

def serialize_book(book):
    return {
        "_id": str(book["_id"]),
        "fileName": book.get("fileName"),
        "bookName": book.get("bookName"),
        "author": book.get("author"),
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

# Create a new book with metadata
def create_book(mongo, book_data):
    result = mongo.db[BOOK_COLLECTION].insert_one(book_data)
    return str(result.inserted_id)

# Fetch all books (Admin/BM/PM/User)
def get_all_books(mongo):
    books = mongo.db[BOOK_COLLECTION].find()
    return [serialize_book(book) for book in books]

# Fetch one book by ID
def get_book_by_id(mongo, book_id):
    book = mongo.db[BOOK_COLLECTION].find_one({"_id": ObjectId(book_id)})
    if not book:
        return None
    return serialize_book(book)

# Fetch books for a specific project
def get_books_by_project(mongo, project_id):
    project = mongo.db[PROJECT_COLLECTION].find_one({"_id": ObjectId(project_id)})
    if not project or not project.get("bookIds"):
        return []
    book_ids = [ObjectId(bid) for bid in project["bookIds"]]
    books = mongo.db[BOOK_COLLECTION].find({"_id": {"$in": book_ids}})
    return [serialize_book(book) for book in books]

# Update book metadata
def update_book(mongo, book_id, update_fields):
    update_fields["updatedAt"] = datetime.now(timezone.utc)
    result = mongo.db[BOOK_COLLECTION].update_one(
        {"_id": ObjectId(book_id)},
        {"$set": update_fields}
    )
    return result.modified_count > 0

# Delete a book
def delete_book(mongo, book_id):
    result = mongo.db[BOOK_COLLECTION].delete_one({"_id": ObjectId(book_id)})
    return result.deleted_count > 0

# Get books uploaded by a user
def get_books_by_creator(mongo, user_id):
    books = mongo.db[BOOK_COLLECTION].find({"createdBy": ObjectId(user_id)})
    return [serialize_book(book) for book in books]