import os
from datetime import timedelta


class Config:
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/ktb")
    JWT_SECRET_KEY = os.getenv("keepsecure", "NOTHINGISECURE")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=12)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=7)

    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app", "uploads")
    BOOK_UPLOAD_DIR = os.path.join(UPLOAD_FOLDER, "books")
    AVATAR_UPLOAD_DIR = os.path.join(UPLOAD_FOLDER, "avatar")
    
    ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}