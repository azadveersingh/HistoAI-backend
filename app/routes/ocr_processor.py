import os
import subprocess
import time
import re
import json
from pathlib import Path
import shutil
import numpy
from ..extensions import mongo, socketio  # Import socketio
from ..models import ocr_model
from ..config import Config
from datetime import datetime, timezone
import torch,gc


# ========================== CONFIG ==========================

os.environ["RECOGNITION_BATCH_SIZE"] = "512"
os.environ["MKL_SERVICE_FORCE_INTEL"] = "1"  
SURYA_ENV = "ocr-llm-surya"
TASK_NAME = "ocr_with_boxes"

# ====================== UTILITY FUNCTIONS ======================

def get_pdf_name(file_path):
    """Extract filename (without .pdf) from full path"""
    return Path(file_path).stem

def extract_page_num(filename):
    """Get numeric page index from filename like *_5_text.png"""
    match = re.search(r"_(\d+)_text\.png$", filename)
    return int(match.group(1)) if match else -1

def get_surya_output_folder(base_output, pdf_name):
    """Surya creates folder: output/pdf_name/"""
    return os.path.join(base_output, pdf_name)

# ======================== OCR FUNCTION =========================

def run_surya_ocr(pdf_path, output_dir, book_id):
    """Run Surya-OCR on input PDF and emit WebSocket progress events"""
    print("🔍 Running Surya-OCR...")
    socketio.emit("book_progress", {
        "book_id": book_id,
        "status": "start_ocr_processing",
        "message": f"Starting OCR processing for {os.path.basename(pdf_path)}"
    })
    
    cmd = [
        "surya_ocr", pdf_path,
        "--task_name", TASK_NAME,
        "--images",
        "--output_dir", output_dir,
        "--disable_math"
    ]
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print("✅ OCR complete.\n")
        socketio.emit("book_progress", {
            "book_id": book_id,
            "status": "ocr_done",
            "message": f"OCR completed for {os.path.basename(pdf_path)}"
        })
        return True, None
    except subprocess.CalledProcessError as e:
        error_msg = f"Surya-OCR failed: {str(e)}\nOutput: {e.output}\nError: {e.stderr}"
        print(f"❌ {error_msg}")
        socketio.emit("book_progress", {
            "book_id": book_id,
            "status": "error",
            "message": f"OCR failed for {os.path.basename(pdf_path)}: {error_msg}"
        })
        return False, error_msg

# =================== TEXT GENERATOR ===================

def extract_text_to_txt(results_json_path, output_txt_path, pdf_name, book_id):
    """Extract text from Surya's JSON into a structured TXT and emit progress events"""
    print("📝 Extracting text to TXT...")
    socketio.emit("book_progress", {
        "book_id": book_id,
        "status": "processing",
        "message": f"Extracting OCR text for {pdf_name}",
        "progress": 50
    })

    if not os.path.exists(results_json_path):
        error_msg = f"results.json not found: {results_json_path}"
        socketio.emit("book_progress", {
            "book_id": book_id,
            "status": "error",
            "message": error_msg
        })
        raise FileNotFoundError(f"❌ {error_msg}")

    with open(results_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    pages = data.get(pdf_name, [])
    total_pages = len(pages)

    print(f"📄 Total pages detected: {total_pages}")
    socketio.emit("book_progress", {
        "book_id": book_id,
        "status": "total_pages",
        "message": f"Book {pdf_name} has {total_pages} pages",
        "total_pages": total_pages
    })

    pagewise_output = []

    for idx, page_data in enumerate(pages):
        page_number = idx + 1
        progress_percent = round((page_number / total_pages) * 100, 2)

        print(f"➡️ Processing page {page_number}/{total_pages} ({progress_percent}%)")
        socketio.emit("book_progress", {
            "book_id": book_id,
            "status": "processing",
            "message": f"Processing page {page_number}/{total_pages} for {pdf_name}",
            "progress": progress_percent
        })

        pagewise_output.append(f"<----- Page {page_number} ----->")

        lines = page_data.get("text_lines", [])
        for line in lines:
            text = line.get("text", "").strip()
            if text:
                pagewise_output.append(text)

        pagewise_output.append(f"<----- Page {page_number} ----->\n")

    with open(output_txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(pagewise_output))

    print(f"✅ Text saved to: {output_txt_path}")
    socketio.emit("book_progress", {
        "book_id": book_id,
        "status": "ocr_done",
        "message": f"OCR text extraction completed for {pdf_name}",
        "progress": 100
    })

# ============================ MAIN ============================
def process_book_ocr(book_id, pdf_path):
    """Process OCR for a book, update the OCR process in the database, and emit WebSocket events"""
    start_time = time.time()
    pdf_name = get_pdf_name(pdf_path)
    book_dir = os.path.join(Config.BOOK_UPLOAD_DIR, book_id)
    output_txt_path = os.path.join(book_dir, "OCR_OUTPUT.TXT")
    surya_output_dir = os.path.join(book_dir, "surya_temp")
    results_json_path = os.path.join(surya_output_dir, pdf_name, "results.json")

    os.makedirs(book_dir, exist_ok=True)
    os.makedirs(surya_output_dir, exist_ok=True)

    ocr_process = ocr_model.get_ocr_process_by_book(mongo, book_id)
    if not ocr_process:
        socketio.emit("book_progress", {
            "book_id": book_id,
            "status": "error",
            "message": f"OCR process not found for book ID {book_id}"
        })
        return False, "OCR process not found"

    # Emit book received event
    socketio.emit("book_progress", {
        "book_id": book_id,
        "status": "book_received",
        "message": f"Book {pdf_name} received for OCR processing"
    })

    # Update OCR process to processing
    ocr_model.update_ocr_process(mongo, ocr_process["_id"], {
        "status": "processing",
        "progress": 0,
        "updatedAt": datetime.now(timezone.utc)
    })

    # Run Surya OCR
    success, error_message = run_surya_ocr(pdf_path, surya_output_dir, book_id)
    if not success:
        ocr_model.update_ocr_process(mongo, ocr_process["_id"], {
            "status": "failed",
            "errorMessage": error_message,
            "progress": 0,
            "updatedAt": datetime.now(timezone.utc)
        })
        return False, error_message

    # Update progress after OCR
    ocr_model.update_ocr_process(mongo, ocr_process["_id"], {
        "progress": 50,
        "updatedAt": datetime.now(timezone.utc)
    })

    try:
        # Extract text to TXT
        extract_text_to_txt(results_json_path, output_txt_path, pdf_name, book_id)
        ocr_model.update_ocr_process(mongo, ocr_process["_id"], {
            "progress": 100,
            "status": "completed",
            "ocrTextFilePath": output_txt_path,
            "completedAt": datetime.now(timezone.utc),
            "updatedAt": datetime.now(timezone.utc)
        })

        print(f"\n🎉 OCR processing done in {round(time.time() - start_time, 2)} seconds.")
        return True, "OCR processing completed successfully"

    except Exception as e:
        error_message = f"OCR processing failed: {str(e)}"
        socketio.emit("book_progress", {
            "book_id": book_id,
            "status": "error",
            "message": error_message
        })
        ocr_model.update_ocr_process(mongo, ocr_process["_id"], {
            "status": "failed",
            "errorMessage": error_message,
            "progress": 0,
            "updatedAt": datetime.now(timezone.utc)
        })
        print(f"❌ {error_message}")
        return False, error_message

    finally:
        if os.path.exists(surya_output_dir):
            shutil.rmtree(surya_output_dir)

        # ✅ Release CUDA memory after each book OCR
        try:
            
            gc.collect()  # free unused Python objects
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
                print("🧹 CUDA memory cleared after book OCR")
        except Exception as e:
            print(f"⚠️ CUDA memory release skipped: {e}")
