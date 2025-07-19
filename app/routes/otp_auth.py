from flask import Blueprint, request, jsonify
from datetime import datetime, timezone
import random
import smtplib
import os
from email.mime.text import MIMEText
from dotenv import load_dotenv
from bson.objectid import ObjectId
from ..models.user import User
from ..extensions import bcrypt, mongo

# Load email config from .env
load_dotenv()
EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_PORT = int(os.getenv("EMAIL_PORT"))
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")

otp_bp = Blueprint("otp", __name__, url_prefix="/api")

temp_otps = {}

@otp_bp.route("/register-init", methods=["POST"])
def register_init():
    data = request.get_json()
    first_name = data.get("firstName")
    last_name = data.get("lastName")
    email = data.get("email")
    password = data.get("password")
    confirm_password = data.get("confirmPassword")
    print(f"Received data {data}")

    if not all([first_name, last_name, email, password, confirm_password]):
        missing_fields = [key for key, value in {
            "firstName": first_name,
            "lastName": last_name,
            "email": email,
            "password": password,
            "confirmPassword": confirm_password
        }.items() if not value]
        print(f"Missing fields: {missing_fields}")
        return jsonify({"message": f"All fields are required. Missing: {missing_fields}"}), 400
    
    if password != confirm_password:
        print("Passwords do not match")
        return jsonify({"message": "Passwords do not match"}), 400
    if len(password) < 8:
        print(f"Password length invalid: {len(password)} characters")
        return jsonify({"message": "Password must be at least 8 characters long"}), 400
    if User.find_by_email(email):
        print(f"User already exists: {email}")
        return jsonify({"message": "User already exists"}), 400

    full_name = f"{first_name.strip()} {last_name.strip()}"
    # Create user with isVerified = False
    user_id = User.create(full_name, email, password, isVerified=False)

    otp = str(random.randint(100000, 999999))
    expiry = datetime.now(timezone.utc) + timedelta(minutes=10)

    mongo.db.users.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {
            "otpCode": otp,
            "otpExpiry": expiry,
            "otpVerified": False
        }}
    )


    try:
        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; background-color: #f4f4f4; padding: 30px;">
            <div style="max-width: 600px; margin: auto; background-color: #ffffff; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.05); overflow: hidden;">
            <div style="background-color: #003366; padding: 20px; text-align: center;">
                <img src="https://raw.githubusercontent.com/Coding-with-Gaurav/KTB-LLM-web/refs/heads/main/graphiti1.png" alt="Company Logo" style="max-height: 50px;" />
                <h2 style="color: white; margin: 10px 0 0;">Histo AI wants to verify your email</h2>
            </div>
            <div style="padding: 30px; color: #333;">
                <p>Dear <strong>{full_name}</strong>,</p>
                <p>Thank you for registering. Please use the following One Time Password (OTP) to verify your email address:</p>
                <p style="font-size: 22px; font-weight: bold; letter-spacing: 2px; color: #003366;">{otp}</p>
                <p>This OTP is valid for <strong>10 minutes</strong>.</p>
                <p>If you did not initiate this request, please ignore this email.</p>
                <p>Regards,<br><strong>Graphiti Multimedia</strong></p>
            </div>
            <div style="background-color: #f1f1f1; text-align: center; padding: 15px; font-size: 12px; color: #777;">
                © {datetime.now(timezone.utc).year} Graphiti Multimedia. All rights reserved.
            </div>
            </div>
        </body>
        </html>
        """

        msg = MIMEText(html_content, "html")
        msg["Subject"] = "Verify Your Email - OTP Inside"
        msg["From"] = EMAIL_USER
        msg["To"] = email


        smtp = smtplib.SMTP(EMAIL_HOST, EMAIL_PORT)
        smtp.starttls()
        smtp.login(EMAIL_USER, EMAIL_PASS)
        smtp.send_message(msg)
        smtp.quit()

        return jsonify({"message": "OTP sent for verification", "temp_token": email}), 200

    except Exception as e:
        return jsonify({"message": "Failed to send OTP", "error": str(e)}), 500


@otp_bp.route("/verify-register-otp", methods=["POST"])
def verify_register_otp():
    data = request.get_json()
    email = data.get("temp_token")
    otp_input = data.get("otp")

    user = User.find_by_email(email)
    if not user:
        return jsonify({"message": "User not found"}), 404

    if (
        user.get("otpCode") != otp_input or
        user.get("otpExpiry") < datetime.now(timezone.utc)
    ):
        return jsonify({"message": "Invalid or expired OTP"}), 401

    mongo.db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {
            "isVerified": True,
            "otpVerified": True,
            "otpCode": None,
            "otpExpiry": None,
            "updatedAt": datetime.now(timezone.utc)
        }}
    )



    user = User.find_by_email(email)
    if not user:
        return jsonify({"message": "User not found"}), 404

    # Update isVerified flag
    mongo.db.users.update_one({"_id": user["_id"]}, {"$set": {"isVerified": True}})

    return jsonify({"message": "Email verified successfully. Please login now."}), 200
