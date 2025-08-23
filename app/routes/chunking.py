
import fitz  # PyMuPDF
from typing import List, Tuple
from stanza import Pipeline
from ..extensions import socketio, mongo
from ..models import ocr_model
import os
import csv
import re
from ..config import Config

nlp = Pipeline(lang='en', processors='tokenize')

def extract_text_data(text: str) -> str:
    """
    Extracts only the main text content from the OCR-like extracted text format.
    Removes tags such as Page Headers, Section Headers, Tables, Extracted Images, etc.
    If no text is found, returns an empty string.
    """
    pattern = r"Text:\s*\n(.*?)(?=\n- None|\nTables:|\Z)"
    matches = re.findall(pattern, text, flags=re.DOTALL)
    cleaned_texts = [
        m.strip() for m in matches
        if m.strip() and m.strip() not in ["- None", "None"]
    ]
    return "\n\n".join(cleaned_texts)

def extract_full_text(file_path: str) -> str:
    """
    Extracts the entire text from the PDF as one string.
    """
    doc = fitz.open(file_path)
    all_text = []

    for page in doc:
        text = page.get_text("text").strip()
        if text:
            all_text.append(text)

    return "\n".join(all_text)

def read_ocr_text(book_id: str) -> str:
    """
    Reads text from the OCR output file stored in the database.
    """
    try:
        ocr_process = ocr_model.get_ocr_process_by_book(mongo, book_id)
        if not ocr_process or not ocr_process.get("ocrTextFilePath"):
            socketio.emit("book_progress", {
                "book_id": book_id,
                "status": "error",
                "message": f"OCR process or text file not found for book ID {book_id}"
            })
            return ""
        
        ocr_file_path = ocr_process["ocrTextFilePath"]
        if not os.path.exists(ocr_file_path):
            socketio.emit("book_progress", {
                "book_id": book_id,
                "status": "error",
                "message": f"OCR text file not found at {ocr_file_path}"
            })
            return ""
        
        with open(ocr_file_path, 'r', encoding='utf-8') as f:
            raw_text = f.read().strip()
        # Clean the OCR text to remove metadata
        cleaned_text = extract_text_data(raw_text)
        return cleaned_text if cleaned_text else ""
    except Exception as e:
        socketio.emit("book_progress", {
            "book_id": book_id,
            "status": "error",
            "message": f"Error reading OCR text file: {str(e)}"
        })
        return ""

def is_text_garbled(text: str, non_alphanumeric_threshold: float = 0.4) -> bool:
    """
    Checks if the text is likely garbled by calculating the proportion of non-alphanumeric characters.
    Args:
        text: The extracted text to check.
        non_alphanumeric_threshold: Maximum allowed proportion of non-alphanumeric characters.
    Returns:
        True if the text is likely garbled, False otherwise.
    """
    if not text:
        return True
    cleaned_text = text.replace(" ", "").replace("\n", "")
    if len(cleaned_text) < 100:  # Too short to be meaningful
        return True
    non_alphanumeric = len(re.sub(r'[a-zA-Z0-9]', '', cleaned_text))
    proportion = non_alphanumeric / len(cleaned_text)
    return proportion > non_alphanumeric_threshold

def stanza_chunker(text: str, chunk_size: int = 512, max_overlap_sentences: int = 4) -> List[str]:
    """
    Splits text into chunks using Stanza's sentence tokenizer and a token length threshold.
    """
    doc = nlp(text)
    sentences = doc.sentences

    chunks = []
    current_chunk = []
    current_length = 0

    for sentence in sentences:
        sent_text = sentence.text.strip()
        sent_length = len(sentence.tokens)

        if current_length + sent_length > chunk_size and current_chunk:
            chunks.append(" ".join(current_chunk).strip())
            overlap_start = max(0, len(current_chunk) - max_overlap_sentences)
            current_chunk = current_chunk[overlap_start:]
            current_length = sum(len(s.split()) for s in current_chunk)

        current_chunk.append(sent_text)
        current_length += sent_length

    if current_chunk:
        chunks.append(" ".join(current_chunk).strip())

    return chunks

def process_and_get_chunks(file_path: str, book_dir: str, filename: str, book_id: str) -> Tuple[List[Tuple[int, str, str]], str]:
    """
    Processes the entire PDF, chunks the text, saves to CSV, and returns chunks and CSV path.
    Falls back to cleaned OCR text if direct text extraction fails, is insufficient, or produces garbled text.
    Emits WebSocket events for chunking progress.
    Args:
        file_path: Path to the PDF file.
        book_dir: Folder path (e.g., Uploads/books/<bookID>).
        filename: Name of the PDF file.
        book_id: ID of the book for WebSocket events.
    Returns:
        Tuple of (list of (chunk_id, chunk_text, source_url), csv_file_path).
    """
    try:
        # Emit start chunking event
        socketio.emit("book_progress", {
            "book_id": book_id,
            "status": "start_chunking",
            "message": f"Starting chunking for {filename}"
        })

        # Extract text directly from PDF
        full_text = extract_full_text(file_path)
        
        # Check if extracted text is empty or likely garbled
        if is_text_garbled(full_text):
            socketio.emit("book_progress", {
                "book_id": book_id,
                "status": "warning",
                "message": f"Direct text extraction for {filename} produced insufficient or garbled text. Attempting to use OCR text."
            })
            full_text = read_ocr_text(book_id)
            if not full_text:
                socketio.emit("book_progress", {
                    "book_id": book_id,
                    "status": "error",
                    "message": f"Failed to read OCR text for {filename}. No text available for chunking."
                })
                return [], ""
            print(f"📄 Using cleaned OCR text for chunking {filename}.")
            socketio.emit("book_progress", {
                "book_id": book_id,
                "status": "processing",
                "message": f"Using cleaned OCR text for chunking {filename}."
            })
        else:
            print(f"📄 Using direct PDF text for chunking {filename}.")
            socketio.emit("book_progress", {
                "book_id": book_id,
                "status": "processing",
                "message": f"Using direct PDF text for chunking {filename}."
            })

        # Proceed with chunking
        chunks = stanza_chunker(full_text)
        if not chunks:
            socketio.emit("book_progress", {
                "book_id": book_id,
                "status": "error",
                "message": f"No chunks generated for {filename}."
            })
            return [], ""

        # Define CSV path
        csv_filename = f"{os.path.splitext(filename)[0]}.csv"
        csv_file_path = os.path.join(book_dir, "Data Extraction", csv_filename)

        # Ensure Data Extraction directory exists
        os.makedirs(os.path.dirname(csv_file_path), exist_ok=True)

        # Save chunks to CSV
        chunk_results = []
        with open(csv_file_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['Chunk ID', 'Text Chunk', 'Source URL'])
            for idx, chunk in enumerate(chunks, start=1):
                source_url = f"books/{book_id}/{filename}#page={idx}"
                writer.writerow([idx, chunk, source_url])
                chunk_results.append((idx, chunk, source_url))

        # Emit chunking completed event
        socketio.emit("book_progress", {
            "book_id": book_id,
            "status": "chunking_completed",
            "message": f"Chunking completed for {filename}, {len(chunks)} chunks created"
        })

        return chunk_results, csv_file_path

    except Exception as e:
        # Emit error event
        socketio.emit("book_progress", {
            "book_id": book_id,
            "status": "error",
            "message": f"Chunking failed for {filename}: {str(e)}"
        })
        print(f"❌ Error: {e}")
        return [], ""