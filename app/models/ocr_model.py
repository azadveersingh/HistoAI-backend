from bson import ObjectId
from datetime import datetime, timezone
import logging

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

OCR_PROCESS_COLLECTION = "ocr_process"

def serialize_ocr_process(ocr_process):
    try:
        completed_at = ocr_process.get("completedAt")
        # Convert float timestamp to datetime if necessary
        if isinstance(completed_at, (int, float)):
            completed_at = datetime.fromtimestamp(completed_at, tz=timezone.utc)
        
        return {
            "_id": str(ocr_process.get("_id", "")),
            "bookId": str(ocr_process.get("bookId", "")),
            "status": ocr_process.get("status", "pending"),
            "progress": ocr_process.get("progress", 0),
            "ocrTextFilePath": ocr_process.get("ocrTextFilePath", None),
            "ocrChunksCsvPath": ocr_process.get("ocrChunksCsvPath", None),
            "errorMessage": ocr_process.get("errorMessage", None),
            "startedAt": ocr_process.get("startedAt", datetime.now(timezone.utc)).isoformat(),
            "completedAt": completed_at.isoformat() if completed_at else None,
            "updatedAt": ocr_process.get("updatedAt", datetime.now(timezone.utc)).isoformat()
        }
    except Exception as e:
        logger.error(f"Error serializing ocr_process: {str(e)}, ocr_process: {ocr_process}")
        raise

def create_ocr_process(mongo, book_id):
    try:
        ocr_process_data = {
            "bookId": ObjectId(book_id),
            "status": "pending",
            "progress": 0,
            "ocrTextFilePath": None,
            "ocrChunksCsvPath": None,
            "errorMessage": None,
            "startedAt": datetime.now(timezone.utc),
            "completedAt": None,
            "updatedAt": datetime.now(timezone.utc)
        }
        result = mongo.db[OCR_PROCESS_COLLECTION].insert_one(ocr_process_data)
        return str(result.inserted_id)
    except Exception as e:
        logger.error(f"Error creating ocr_process for book_id {book_id}: {str(e)}")
        raise

def get_ocr_process_by_book(mongo, book_id):
    try:
        ocr_process = mongo.db[OCR_PROCESS_COLLECTION].find_one({"bookId": ObjectId(book_id)})
        if not ocr_process:
            return None
        return serialize_ocr_process(ocr_process)
    except Exception as e:
        logger.error(f"Error getting ocr_process for book_id {book_id}: {str(e)}")
        raise

def get_all_ocr_processes(mongo):
    try:
        ocr_processes = mongo.db[OCR_PROCESS_COLLECTION].find()
        return [serialize_ocr_process(ocr_process) for ocr_process in ocr_processes]
    except Exception as e:
        logger.error(f"Error getting all ocr_processes: {str(e)}")
        raise

def update_ocr_process(mongo, ocr_process_id, update_fields):
    try:
        update_fields["updatedAt"] = datetime.now(timezone.utc)
        result = mongo.db[OCR_PROCESS_COLLECTION].update_one(
            {"_id": ObjectId(ocr_process_id)},
            {"$set": update_fields}
        )
        return result.modified_count > 0
    except Exception as e:
        logger.error(f"Error updating ocr_process {ocr_process_id}: {str(e)}")
        raise

def mark_ocr_process_complete(mongo, book_id):
    try:
        ocr_process = mongo.db[OCR_PROCESS_COLLECTION].find_one({"bookId": ObjectId(book_id)})
        if not ocr_process:
            return False
        update_fields = {
            "status": "completed",
            "progress": 100,
            "completedAt": datetime.now(timezone.utc),
            "updatedAt": datetime.now(timezone.utc)
        }
        return update_ocr_process(mongo, ocr_process["_id"], update_fields)
    except Exception as e:
        logger.error(f"Error marking ocr_process complete for book_id {book_id}: {str(e)}")
        raise