from ..extensions import mongo, bcrypt
from bson.objectid import ObjectId
import pymongo
from datetime import datetime, timezone

class UserRoles:
    USER = "user"
    PM = "project_manager"
    BM = "book_manager"
    ADMIN = "admin"
    @classmethod
    def values(cls):
        return [cls.USER, cls.PM, cls.BM, cls.ADMIN]

class User:
    def __init__(self, user_data):
        self.user_data = user_data

    @staticmethod
    def create(fullName, email, password, isVerified=False):
        hashed_password = bcrypt.generate_password_hash(password).decode("utf-8")
        user_data = {
            "fullName": fullName,
            "email": email,
            "password": hashed_password,
            "isVerified": isVerified,
            "otpVerified": False,
            "otpCode": None,
            "otpExpiry": None,
            "resetToken": None,
            "resetTokenExpiry": None,
            "isBlocked": False,
            "isActive": False,  # default to False until admin activates
            "isLocked": False,
            "loginAttempts": 0,
            "role": "user",
            "avatar": None,
            "createdAt": datetime.now(timezone.utc),
            "updatedAt": datetime.now(timezone.utc),
            "lastLogin": None
        }
        result = mongo.db.users.insert_one(user_data)
        return str(result.inserted_id)

    @staticmethod
    def find_by_email(email):
        return mongo.db.users.find_one({"email": email})

    @staticmethod
    def find_by_id(user_id):
        try:
            return mongo.db.users.find_one({"_id": ObjectId(user_id)})
        except:
            return None

    @staticmethod
    def find_by_ids(user_ids):
        try:
            users = mongo.db.users.find({"_id": {"$in": [ObjectId(uid) for uid in user_ids]}})
            return [
                {
                    "_id": str(user["_id"]),
                    "fullName": user.get("fullName"),
                    "email": user.get("email"),
                    "role": user.get("role", "user"),
                    "isActive": user.get("isActive", False),
                    "isBlocked": user.get("isBlocked", False),
                    "createdAt": user.get("createdAt")
                }
                for user in users
            ]
        except:
            return []

    @staticmethod
    def find_one_and_update(query, update, return_document=False):
        return mongo.db.users.find_one_and_update(
            query,
            update,
            return_document=pymongo.ReturnDocument.AFTER if return_document else pymongo.ReturnDocument.BEFORE
        )

    @staticmethod
    def get_all_users():
        users = mongo.db.users.find()
        return [
            {
                "_id": str(user["_id"]),
                "fullName": user.get("fullName"),
                "email": user.get("email"),
                "role": user.get("role", "user"),
                "isActive": user.get("isActive", False),
                "isBlocked": user.get("isBlocked", False),
                "createdAt": user.get("createdAt")
            }
            for user in users
        ]