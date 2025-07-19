from bson import ObjectId
from datetime import datetime, timezone

def serialize_project(project):
    return {
        "_id": str(project["_id"]),
        "name": project["name"],
        "memberIds": [str(mid) for mid in project.get("memberIds", [])],
        "collectionIds": [str(cid) for cid in project.get("collectionIds", [])],
        "bookIds": [str(bid) for bid in project.get("bookIds", [])],
        "chatHistoryId": str(project.get("chatHistoryId", "")) if project.get("chatHistoryId") else None,
        "createdBy": str(project.get("createdBy", "")) if project.get("createdBy") else None,
        "createdAt": project.get("createdAt", datetime.now(timezone.utc)).isoformat(),
        "updatedAt": project.get("updatedAt", datetime.now(timezone.utc)).isoformat(),
    }

COLLECTION_NAME = "project-details"
# Get all projects
def get_all_projects(mongo):
    projects = mongo.db["project-details"].find()
    return [serialize_project(p) for p in projects]

def get_project_by_id(mongo, project_id):
    project = mongo.db[COLLECTION_NAME].find_one({"_id": ObjectId(project_id)})
    if project:
        project["_id"] = str(project["_id"])
    return project

def create_project(mongo, project_data):
    result = mongo.db[COLLECTION_NAME ].insert_one(project_data)
    return result.inserted_id

def update_project(mongo, project_id, update_fields):
    result = mongo.db[COLLECTION_NAME ].update_one(
        {"_id": ObjectId(project_id)},
        {"$set": update_fields}
    )
    return result.modified_count > 0

def delete_project(mongo, project_id):
    result = mongo.db[COLLECTION_NAME ].delete_one({"_id": ObjectId(project_id)})
    return result.deleted_count > 0

def get_projects_by_creator(mongo, user_id):
    projects = mongo.db["project-details"].find({
        "createdBy": ObjectId(user_id)
    })
    return [serialize_project(p) for p in projects]


def get_projects_by_member(mongo, user_id):
    return list(
        mongo.db.projects.find({
            "memberIds": ObjectId(user_id)
        })
    )

