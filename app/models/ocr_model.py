from bson import ObjectId
from datetime import datetime, timezone

OCR_PROCESS_COLLECTION = "ocr_process"

def serialize_ocr_process(ocr_process):
    return {
        "_id": str(ocr_process["_id"]),
        "bookId": str(ocr_process["bookId"]),
        "status": ocr_process.get("status", "pending"),
        "progress": ocr_process.get("progress", 0),
        "ocrTextFilePath": ocr_process.get("ocrTextFilePath"),
        "ocrChunksCsvPath": ocr_process.get("ocrChunksCsvPath"),
        "errorMessage": ocr_process.get("errorMessage"),
        "startedAt": ocr_process.get("startedAt", datetime.now(timezone.utc)).isoformat(),
        "completedAt": ocr_process.get("completedAt").isoformat() if ocr_process.get("completedAt") else None
    }

def create_ocr_process(mongo, book_id):
    ocr_process_data = {
        "bookId": ObjectId(book_id),
        "status": "pending",
        "progress": 0,
        "ocrTextFilePath": None,
        "ocrChunksCsvPath": None,
        "errorMessage": None,
        "startedAt": datetime.now(timezone.utc),
        "completedAt": None
    }
    result = mongo.db[OCR_PROCESS_COLLECTION].insert_one(ocr_process_data)
    return str(result.inserted_id)

def get_ocr_process_by_book(mongo, book_id):
    ocr_process = mongo.db[OCR_PROCESS_COLLECTION].find_one({"bookId": ObjectId(book_id)})
    if not ocr_process:
        return None
    return serialize_ocr_process(ocr_process)

def get_all_ocr_processes(mongo):
    ocr_processes = mongo.db[OCR_PROCESS_COLLECTION].find()
    return [serialize_ocr_process(ocr_process) for ocr_process in ocr_processes]

def update_ocr_process(mongo, ocr_process_id, update_fields):
    update_fields["updatedAt"] = datetime.now(timezone.utc)
    result = mongo.db[OCR_PROCESS_COLLECTION].update_one(
        {"_id": ObjectId(ocr_process_id)},
        {"$set": update_fields}
    )
    return result.modified_count > 0

def mark_ocr_process_complete(mongo, book_id):
    ocr_process = mongo.db[OCR_PROCESS_COLLECTION].find_one({"bookId": ObjectId(book_id)})
    if not ocr_process:
        return False
    update_fields = {
        "status": "completed",
        "progress": 100,
        "completedAt": datetime.now(timezone.utc)
    }
    return update_ocr_process(mongo, ocr_process["_id"], update_fields)