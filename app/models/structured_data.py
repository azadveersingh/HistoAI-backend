from bson import ObjectId
from datetime import datetime, timezone
from ..extensions import mongo

STRUCTURED_DATA_COLLECTION = "structured_data"

class StructuredData:
    @staticmethod
    def create(mongo, structured_data):
        result = mongo.db[STRUCTURED_DATA_COLLECTION].insert_one(structured_data)
        return str(result.inserted_id)

    @staticmethod
    def get_by_id(mongo, structured_data_id):
        data = mongo.db[STRUCTURED_DATA_COLLECTION].find_one({"_id": ObjectId(structured_data_id)})
        if not data:
            return None
        return {
            "_id": str(data["_id"]),
            "bookId": str(data["bookId"]),
            "status": data.get("status", "pending"),
            "structuredDataPath": data.get("structuredDataPath"),
            "totalChunks": data.get("totalChunks", 0),
            "processedChunks": data.get("processedChunks", 0),
            "errorMessage": data.get("errorMessage"),
            "startedAt": data.get("startedAt", datetime.now(timezone.utc)).isoformat(),
            "completedAt": data.get("completedAt").isoformat() if data.get("completedAt") else None,
            "updatedAt": data.get("updatedAt", datetime.now(timezone.utc)).isoformat()
        }

    @staticmethod
    def get_by_book(mongo, book_id):
        data = mongo.db[STRUCTURED_DATA_COLLECTION].find_one({"bookId": ObjectId(book_id)})
        if not data:
            return None
        return StructuredData.get_by_id(mongo, str(data["_id"]))

    @staticmethod
    def update(mongo, structured_data_id, update_fields):
        update_fields["updatedAt"] = datetime.now(timezone.utc)
        result = mongo.db[STRUCTURED_DATA_COLLECTION].update_one(
            {"_id": ObjectId(structured_data_id)},
            {"$set": update_fields}
        )
        return result.modified_count > 0

    @staticmethod
    def get_all(mongo):
        return [
            {
                "_id": str(data["_id"]),
                "bookId": str(data["bookId"]),
                "status": data.get("status", "pending"),
                "structuredDataPath": data.get("structuredDataPath"),
                "totalChunks": data.get("totalChunks", 0),
                "processedChunks": data.get("processedChunks", 0),
                "errorMessage": data.get("errorMessage"),
                "startedAt": data.get("startedAt", datetime.now(timezone.utc)).isoformat(),
                "completedAt": data.get("completedAt").isoformat() if data.get("completedAt") else None,
                "updatedAt": data.get("updatedAt", datetime.now(timezone.utc)).isoformat()
            }
            for data in mongo.db[STRUCTURED_DATA_COLLECTION].find()
        ]