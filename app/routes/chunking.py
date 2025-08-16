import fitz  # PyMuPDF
from typing import List, Tuple
from stanza import Pipeline
from ..extensions import socketio
import os
import csv
from ..config import Config

nlp = Pipeline(lang='en', processors='tokenize')

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

            # Maintain overlap
            overlap_start = max(0, len(current_chunk) - max_overlap_sentences)
            current_chunk = current_chunk[overlap_start:]
            current_length = sum(len(s.split()) for s in current_chunk)

        current_chunk.append(sent_text)
        current_length += sent_length

    if current_chunk:
        chunks.append(" ".join(current_chunk).strip())

    return chunks

def process_and_get_chunks(file_path: str, unique_folder: str, filename: str, book_id: str) -> Tuple[List[Tuple[int, str, str]], str]:
    """
    Processes the entire PDF, chunks the text, saves to CSV, and returns chunks and CSV path.
    Emits WebSocket events for chunking progress.
    Args:
        file_path: Path to the PDF file.
        unique_folder: Folder path (e.g., Uploads/books/<bookID>).
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

        # Extract text
        full_text = extract_full_text(file_path)
        chunks = stanza_chunker(full_text)

        # Define CSV path
        csv_filename = f"{os.path.splitext(filename)[0]}.csv"
        csv_file_path = os.path.join(unique_folder, "Data Extraction", csv_filename)

        # Ensure Data Extraction directory exists
        os.makedirs(os.path.dirname(csv_file_path), exist_ok=True)

        # Save chunks to CSV
        chunk_results = []
        with open(csv_file_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['chunk_id', 'chunk_text', 'source_url'])
            for idx, chunk in enumerate(chunks, start=1):
                source_url = f"{unique_folder}/{filename}#page={idx}"
                writer.writerow([idx, chunk, source_url])
                chunk_results.append((idx, chunk, source_url))

        # Emit chunking completed event
        socketio.emit("book_progress", {
            "book_id": book_id,
            "status": "chunking_completed",
            "message": f"Chunking completed for {filename}, {len(chunks)} chunks created"
        })

        # Emit book processing complete event
        socketio.emit("book_progress", {
            "book_id": book_id,
            "status": "book_processing_complete",
            "message": f"Book processing completed for {filename}"
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