from bson import ObjectId
from datetime import datetime, timezone

COLLECTIONS_COLLECTION = "collections"
PROJECT_COLLECTION = "project-details"

def serialize_collection(doc, mongo):
    project_cursor = mongo.db[PROJECT_COLLECTION].find({
        "collectionIds": {"$in": [doc["_id"]]}
    })
    project_ids = [str(p["_id"]) for p in project_cursor]
    return {
        "_id": str(doc["_id"]),
        "name": doc.get("name"),
        "bookIds": [str(bid) for bid in doc.get("bookIds", [])],
        "projectIds": project_ids,
        "createdBy": str(doc["createdBy"]) if doc.get("createdBy") else None,
        "createdAt": doc.get("createdAt", datetime.now(timezone.utc)).isoformat(),
        "updatedAt": doc.get("updatedAt", datetime.now(timezone.utc)).isoformat(),
    }

def get_visible_collections(mongo, user_id, member_project_ids):
    query = {
        "$or": [
            {"createdBy": ObjectId(user_id)},
            {"_id": {
                "$in": mongo.db[PROJECT_COLLECTION].distinct(
                    "collectionIds",
                    {"_id": {"$in": member_project_ids}}
                )
            }}
        ]
    }
    docs = mongo.db[COLLECTIONS_COLLECTION].find(query)
    return [serialize_collection(d, mongo) for d in docs]

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
    return serialize_collection(doc, mongo) if doc else None

def get_project_collections(mongo, project_id):
    project = mongo.db[PROJECT_COLLECTION].find_one({"_id": ObjectId(project_id)})
    if not project or not project.get("collectionIds"):
        return []
    
    collection_ids = []
    for cid in project["collectionIds"]:
        if isinstance(cid, (str, ObjectId)) and ObjectId.is_valid(cid):
            collection_ids.append(ObjectId(cid))
        else:
            print(f"Invalid collection ID in project {project_id}: {cid}")
    
    if not collection_ids:
        return []
    
    collections = mongo.db[COLLECTIONS_COLLECTION].find({"_id": {"$in": collection_ids}})
    return [serialize_collection(doc, mongo) for doc in collections]

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