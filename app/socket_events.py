from flask_socketio import join_room, emit
from app.extensions import socketio
from flask_jwt_extended import decode_token

@socketio.on("join_room")
def handle_join_room(data):
    token = data.get("token")

    if not token:
        emit("error", {"message": "Missing token"})
        return

    try:
        decoded = decode_token(token)
        user_id = decoded["sub"]
        join_room(user_id)
        emit("joined_room", {"message": f"Joined room {user_id}"})
    except Exception as e:
        emit("error", {"message": f"Invalid token: {str(e)}"})
