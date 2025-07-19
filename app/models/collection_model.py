from bson import ObjectId
from datetime import datetime, timezone

COLLECTIONS_COLLECTION = "collections"

def serialize_collection(doc):
    return {
        "_id": str(doc["_id"]),
        "name": doc.get("name"),
        "bookIds": [str(bid) for bid in doc.get("bookIds", [])],
        "projectId": str(doc["projectId"]) if doc.get("projectId") else None,
        "createdBy": str(doc["createdBy"]) if doc.get("createdBy") else None,
        "createdAt": doc.get("createdAt", datetime.now(timezone.utc)).isoformat(),
        "updatedAt": doc.get("updatedAt", datetime.now(timezone.utc)).isoformat(),
    }


def get_visible_collections(mongo, user_id, member_project_ids):
    query = {
        "$or": [
            {"createdBy": ObjectId(user_id)},
            {"projectId": {"$in": member_project_ids}}  # assume already ObjectId
        ]
    }
    docs = mongo.db[COLLECTIONS_COLLECTION].find(query)
    return [serialize_collection(d) for d in docs]


def create_collection(mongo, data):
    data["createdAt"] = datetime.now(timezone.utc)
    data["updatedAt"] = datetime.now(timezone.utc)
    result = mongo.db[COLLECTIONS_COLLECTION].insert_one(data)
    return str(result.inserted_id)

def get_all_collections(mongo):
    docs = mongo.db[COLLECTIONS_COLLECTION].find()
    return [serialize_collection(d) for d in docs]

def get_collection_by_id(mongo, collection_id):
    doc = mongo.db[COLLECTIONS_COLLECTION].find_one({"_id": ObjectId(collection_id)})
    return serialize_collection(doc) if doc else None

def update_collection(mongo, collection_id, update_data):
    update_data["updatedAt"] = datetime.now(timezone.utc)
    result = mongo.db[COLLECTIONS_COLLECTION].update_one(
        {"_id": ObjectId(collection_id)},
        {"$set": update_data}
    )
    return result.modified_count > 0

def delete_collection(mongo, collection_id):
    result = mongo.db[COLLECTIONS_COLLECTION].delete_one({"_id": ObjectId(collection_id)})
    return result.deleted_count > 0
