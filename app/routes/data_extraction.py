import os
import csv
import json
import time
import requests
from bson import ObjectId
from datetime import datetime, timezone
from ..extensions import mongo, socketio
from ..models import structured_data
from ..config import Config
from dotenv import load_dotenv
import sys

# Load environment variables
load_dotenv()
X_API_KEY = os.getenv("X_API_KEY")

def send_chunks_to_llm(book_id, csv_file_path, book_folder, book_name, user_id, filename, preview_url, file_path, unique_folder_name, selected_llm_url):
    """Sends CSV data as an SSE request and processes responses in real time."""
    print(f"\n📤 Sending chunks content to LLM ({selected_llm_url}) for processing: {csv_file_path}")

    # Count total chunks in CSV
    total_chunks_csv = 0
    with open(csv_file_path, "r", encoding="utf-8") as file:
        reader = csv.reader(file)
        try:
            next(reader)  # Skip header
            total_chunks_csv = sum(1 for _ in reader)
        except Exception as e:
            print(f"❌ Error reading CSV: {str(e)}")
            socketio.emit("upload_status", {
                "book_id": book_id,
                "message": f"Failed to read CSV: {str(e)}",
                "progress": 0,
                "book_id": book_id
            }, room=user_id)
            return {"error": f"Failed to read CSV: {str(e)}"}, 400

    socketio.emit("upload_status", {
        "book_id": book_id,
        "message": f"Total {total_chunks_csv} chunks identified.",
        "total_chunks": total_chunks_csv,
        "progress": 0,
        "book_id": book_id
    }, room=user_id)

    # Create structured data entry in the database
    structured_data_doc = {
        "bookId": ObjectId(book_id),
        "status": "pending",
        "structuredDataPath": None,
        "totalChunks": total_chunks_csv,
        "processedChunks": 0,
        "errorMessage": None,
        "startedAt": datetime.now(timezone.utc),
        "completedAt": None,
        "updatedAt": datetime.now(timezone.utc)
    }
    structured_data_id = structured_data.StructuredData.create(mongo, structured_data_doc)

    # Update book with structuredDataId
    from ..models import book_model
    book_model.update_book(mongo, book_id, {"structuredDataId": ObjectId(structured_data_id)})

    # Read CSV content
    with open(csv_file_path, "r", encoding="utf-8") as file:
        csv_content = file.read()
    print(f"CSV Content Sent: {csv_content}")

    data = {"supporting_data": csv_content}
    headers = {"X-API-KEY": X_API_KEY, "Content-Type": "application/json"}

    # Define structured data output path
    structured_data_filename = f"{os.path.splitext(filename)[0]}_structured.json"
    structured_data_path = os.path.join(book_folder, "Data Extraction", structured_data_filename)

    # Ensure Data Extraction directory exists
    os.makedirs(os.path.join(book_folder, "Data Extraction"), exist_ok=True)

    try:
        # Send request to LLM
        response = requests.post(selected_llm_url, json=data, headers=headers, stream=True, timeout=30)

        if response.status_code != 200:
            print(f"⚠️ {selected_llm_url} connection failed: {response.status_code} - {response.text}")
            socketio.emit("upload_status", {
                "book_id": book_id,
                "message": f"Model connection failed: {response.status_code} - {response.text}",
                "book_id": book_id
            }, room=user_id)
            structured_data.StructuredData.update(mongo, structured_data_id, {
                "status": "failed",
                "errorMessage": f"Model connection failed: {response.status_code} - {response.text}",
                "updatedAt": datetime.now(timezone.utc)
            })
            return {"error": f"Failed to connect to the model: {response.status_code}"}, 500

        print("Model connection successful!")
        socketio.emit("upload_status", {
            "book_id": book_id,
            "message": "Model connection successful!",
            "book_id": book_id
        }, room=user_id)

        with open(structured_data_path, "w", encoding="utf-8") as json_file:
            json_file.write("[")
            first_entry = True
            total_chunks = 0
            start_time = time.time()
            processed_chunks = 0

            print("\n📡 Waiting for response...\n")
            socketio.emit("progress_update", {
                "message": "Processing started...",
                "progress": 0,
                "book_id": book_id
            }, room=user_id)

            for line in response.iter_lines():
                if line:
                    decoded_line = line.decode("utf-8").replace("data: ", "").strip()
                    if decoded_line == "[DONE]":
                        print("Received termination signal [DONE]")
                        continue
                    try:
                        print(f"📥 Model Response: {decoded_line}")
                        socketio.emit("model_response", {
                            "chunk": decoded_line,
                            "book_id": book_id
                        }, room=user_id)

                        chunk_response = json.loads(decoded_line)
                        total_chunks += 1
                        processed_chunks += 1

                        if not first_entry:
                            json_file.write(",\n")
                        first_entry = False

                        json.dump(chunk_response, json_file)

                        progress_percent = int((processed_chunks / total_chunks_csv) * 100) if total_chunks_csv > 0 else 0
                        socketio.emit("progress_update", {
                            "message": f"Processing chunk {processed_chunks}/{total_chunks_csv}...",
                            "progress": progress_percent,
                            "book_id": book_id
                        }, room=user_id)

                        # Update structured data progress
                        structured_data.StructuredData.update(mongo, structured_data_id, {
                            "processedChunks": processed_chunks,
                            "updatedAt": datetime.now(timezone.utc)
                        })

                        sys.stdout.write(f"\r🚀 Received {total_chunks} chunks using {selected_llm_url}...")
                        sys.stdout.flush()

                    except json.JSONDecodeError as json_err:
                        print(f"Invalid JSON: {decoded_line} - {str(json_err)}")
                        continue

            json_file.write("]")

            end_time = time.time()
            print(f"\n✅ Done! Received {total_chunks} chunks in {end_time - start_time:.2f} seconds.")
            socketio.emit("progress_update", {
                "message": f"✅ Processing completed! Total {total_chunks} chunks processed for {book_name}.",
                "progress": 100,
                "book_id": book_id
            }, room=user_id)

            print(f"✅ Structured data successfully saved to {structured_data_path}")

        # Update structured data status (even if no chunks processed)
        structured_data.StructuredData.update(mongo, structured_data_id, {
            "status": "completed" if processed_chunks > 0 else "failed",
            "structuredDataPath": structured_data_path,
            "processedChunks": processed_chunks,
            "completedAt": datetime.now(timezone.utc),
            "updatedAt": datetime.now(timezone.utc),
            "errorMessage": None if processed_chunks > 0 else "No valid chunks processed. Check LLM server response."
        })

        if processed_chunks == 0:
            print("No valid chunks processed, but saving MongoDB record for consistency")
            socketio.emit("upload_status", {
                "book_id": book_id,
                "message": f"No valid chunks processed for {book_name}. Check LLM server response.",
                "progress": 0,
                "book_id": book_id
            }, room=user_id)

        return {"message": "Structured data processed successfully", "structured_data_path": structured_data_path}, 200

    except requests.exceptions.RequestException as e:
        error_message = f"Error communicating with LLM: {str(e)}"
        print(f"❌ {error_message}")
        socketio.emit("upload_status", {
            "book_id": book_id,
            "message": error_message,
            "progress": -1,
            "book_id": book_id
        }, room=user_id)
        structured_data.StructuredData.update(mongo, structured_data_id, {
            "status": "failed",
            "errorMessage": error_message,
            "updatedAt": datetime.now(timezone.utc)
        })
        return {"error": error_message}, 500

    except Exception as e:
        error_message = f"Structured data processing failed: {str(e)}"
        print(f"❌ {error_message}")
        socketio.emit("upload_status", {
            "book_id": book_id,
            "message": error_message,
            "progress": 0,
            "book_id": book_id
        }, room=user_id)
        structured_data.StructuredData.update(mongo, structured_data_id, {
            "status": "failed",
            "errorMessage": error_message,
            "updatedAt": datetime.now(timezone.utc)
        })
        return {"error": error_message}, 500