import random
from datetime import datetime
from bson import ObjectId
from pymongo import MongoClient

# MongoDB connection URI
MONGO_URI = "mongodb+srv://KTB:ktb%402025@cluster0.umatstc.mongodb.net/KTB?retryWrites=true&w=majority&appName=Cluster0"

# Connect to MongoDB
client = MongoClient(MONGO_URI)
db = client["KTB"]
collection = db["project-details"]

# Historical project names
PROJECT_NAMES = [
    "Quit India Movement",
    "Non-Cooperation Movement",
    "Civil Disobedience Movement",
    "Swadeshi Movement",
    "Jallianwala Bagh Massacre",
    "Salt March",
    "Khilafat Movement",
    "Azad Hind Fauj Campaign",
    "Champaran Satyagraha",
    "Simon Commission Protest",
    "Revolutionary Activities of Bhagat Singh",
    "Gadar Movement",
    "Rowlatt Act Resistance",
    "INA Trials"
]

def create_dummy_object_ids(count=3):
    return [ObjectId() for _ in range(count)]

def generate_project_data():
    now = datetime.utcnow()
    return [
        {
            "_id": ObjectId(),
            "name": name,
            "memberIds": create_dummy_object_ids(),
            "collectionIds": create_dummy_object_ids(2),
            "bookIds": create_dummy_object_ids(2),
            "chatHistoryId": ObjectId(),
            "createdBy": ObjectId(),
            "createdAt": now,
            "updatedAt": now
        }
        for name in PROJECT_NAMES
    ]

def main():
    print("Connecting to MongoDB Atlas...")
    try:
        # Optional: clear old entries
        collection.delete_many({})

        data = generate_project_data()
        result = collection.insert_many(data)

        print(f"✅ Successfully inserted {len(result.inserted_ids)} documents into 'project-details'.")
    except Exception as e:
        print("❌ Failed to insert projects:", e)

if __name__ == "__main__":
    main()
