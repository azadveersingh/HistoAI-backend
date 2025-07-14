from functools import wraps
from flask_jwt_extended import get_jwt_identity
from flask import jsonify
from ..models.user import User

def role_required(allowed_roles):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            user_id = get_jwt_identity()
            user = User.find_by_id(user_id)
            if not user or user.get("role") not in allowed_roles:
                return jsonify({"message": "You are not authorized to access this resource."}), 403
            return func(*args, **kwargs)
        return wrapper
    return decorator
