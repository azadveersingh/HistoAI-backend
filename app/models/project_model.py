from bson import ObjectId
from datetime import datetime

def serialize_project(project):
    return {
        "_id": str(project["_id"]),
        "name": project["name"],
        "memberIds": [str(mid) for mid in project.get("memberIds", [])],
        "collectionIds": [str(cid) for cid in project.get("collectionIds", [])],
        "bookIds": [str(bid) for bid in project.get("bookIds", [])],
        "chatHistoryId": str(project.get("chatHistoryId", "")) if project.get("chatHistoryId") else None,
        "createdBy": str(project.get("createdBy", "")) if project.get("createdBy") else None,
        "createdAt": project.get("createdAt", datetime.utcnow()).isoformat(),
        "updatedAt": project.get("updatedAt", datetime.utcnow()).isoformat(),
    }

# Get all projects
def get_all_projects(mongo):
    projects = mongo.db["project-details"].find()
    return [serialize_project(p) for p in projects]

# Get a single project by ID
def get_project_by_id(mongo, project_id):
    project = mongo.db["project-details"].find_one({"_id": ObjectId(project_id)})
    if not project:
        return None
    return serialize_project(project)

# Create a new project
def create_project(mongo, data):
    now = datetime.utcnow()
    data["createdAt"] = now
    data["updatedAt"] = now
    result = mongo.db["Project-details"].insert_one(data)
    return str(result.inserted_id)

# Optional: delete or update functions can be added similarly
