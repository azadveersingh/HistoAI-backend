from ..extensions import mongo, bcrypt
from bson.objectid import ObjectId
import pymongo

from datetime import datetime

class UserRoles:
    USER = "user"
    PM = "pm"
    BM = "bm"
    ADMIN = "admin"

    
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
            "role": "user",  # string type role
            "bio": "",
            "status": "Available",
            "avatar": None,
            "createdAt": datetime.utcnow(),
            "updatedAt": datetime.utcnow(),
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