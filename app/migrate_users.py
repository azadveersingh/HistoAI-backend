from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from datetime import datetime

# MongoDB Atlas URI
MONGO_URI = "mongodb+srv://KTB:ktb%402025@cluster0.umatstc.mongodb.net/KTB?retryWrites=true&w=majority&appName=Cluster0"

# Initialize MongoDB client
try:
    mongo = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    # Test connection
    mongo.admin.command('ping')
    print("Successfully connected to MongoDB Atlas")
    db = mongo.get_database()  # Uses database from MONGO_URI ('KTB')
except ConnectionFailure as e:
    print(f"Failed to connect to MongoDB Atlas: {str(e)}")
    exit(1)

def migrate_users():
    try:
        # Get the 5 most recent documents from the 'users' collection, sorted by _id descending
        users = db.users.find().sort("_id", -1).limit(5)
        
        # Check if users collection is empty
        if not db.users.count_documents({}):
            print("No documents found in 'users' collection")
            return {
                "status": "error",
                "message": "No documents found in 'users' collection",
                "migrated_count": 0,
                "failed_count": 0
            }
        
        # Counter for tracking migrations
        migrated_count = 0
        failed_count = 0
        
        # Iterate through each user document
        for user in users:
            try:
                # Check for duplicate email to avoid inserting duplicates
                if db["user-details"].find_one({"email": user.get("email")}):
                    print(f"Skipped user {user.get('email', 'unknown')} - already exists in user-details")
                    continue
                
                # Prepare user data for insertion
                user_data = {
                    "fullName": user.get("fullName", ""),
                    "email": user.get("email", ""),
                    "password": user.get("password", ""),
                    "isVerified": user.get("isVerified", False),
                    "otpVerified": user.get("otpVerified", False),
                    "otpCode": user.get("otpCode", None),
                    "otpExpiry": user.get("otpExpiry", None),
                    "resetToken": user.get("resetToken", None),
                    "resetTokenExpiry": user.get("resetTokenExpiry", None),
                    "isBlocked": user.get("isBlocked", False),
                    "isActive": user.get("isActive", False),
                    "isLocked": user.get("isLocked", False),
                    "loginAttempts": user.get("loginAttempts", 0),
                    "role": user.get("role", "user"),
                    "bio": user.get("bio", ""),
                    "status": user.get("status", "Available"),
                    "avatar": user.get("avatar", None),
                    "createdAt": user.get("createdAt", datetime.utcnow()),
                    "updatedAt": user.get("updatedAt", datetime.utcnow()),
                    "lastLogin": user.get("lastLogin", None)
                }
                
                # Insert into user-details collection
                result = db["user-details"].insert_one(user_data)
                migrated_count += 1
                print(f"Successfully migrated user: {user.get('email', 'unknown')}")
                
            except Exception as e:
                failed_count += 1
                print(f"Failed to migrate user {user.get('email', 'unknown')}: {str(e)}")
        
        print(f"\nMigration completed. Successfully migrated {migrated_count} users. Skipped or failed: {failed_count}")
        
        return {
            "status": "success",
            "migrated_count": migrated_count,
            "failed_count": failed_count
        }
        
    except Exception as e:
        print(f"Error during migration: {str(e)}")
        return {
            "status": "error",
            "message": str(e),
            "migrated_count": 0,
            "failed_count": 0
        }
    finally:
        # Close the MongoDB connection
        mongo.close()
        print("MongoDB connection closed")

if __name__ == "__main__":
    result = migrate_users()
    print(f"Migration result: {result}")