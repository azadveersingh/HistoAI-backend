import os
from werkzeug.utils import secure_filename
from flask import current_app
import fitz
from PIL import Image
from ..config import Config
import zipfile
from pathlib import Path

def allowed_file(filename):
    return "." in filename and \
           filename.rsplit(".", 1)[1].lower() in current_app.config["ALLOWED_EXTENSIONS"]

def create_book_folder_structure(book_id):
    """Create the folder structure for a book."""
    book_dir = os.path.join(Config.BOOK_UPLOAD_DIR, book_id)
    subdirs = [
        os.path.join(book_dir, "Data Extraction"),
        os.path.join(book_dir, "Chatbot"),
        os.path.join(book_dir, "Knowledge Graph"),
        os.path.join(book_dir, "OCR Text & Images"),
    ]
    for directory in [book_dir] + subdirs:
        os.makedirs(directory, exist_ok=True)
    return book_dir

def create_pdf_preview(book_id, file_path):
    """
    Creates a preview image from the first page of a PDF
    Returns the relative path of the preview image (e.g., <book_id>/<sanitized_filename>.jpg)
    """
    filename = os.path.basename(file_path)
    preview_filename = f"{os.path.splitext(filename)[0]}.jpg"
    book_dir = os.path.join(Config.BOOK_UPLOAD_DIR, book_id)
    preview_path = os.path.join(book_dir, preview_filename)

    try:
        doc = fitz.open(file_path)
        page = doc[0]
        pix = page.get_pixmap()
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        img.save(preview_path, "JPEG")
        print(f"Preview image saved at: {preview_path}")
    except Exception as e:
        print(f"Failed to create preview: {e}")
        raise

    return f"{book_id}/{preview_filename}"

def create_structured_zip(paths, output_zip="custom_archive.zip"):
    """
    Creates a structured ZIP archive with specific folders:
    - extracted_figures/
    - handwritten_text_images/
    - annotated_images/
    - extracted_text.txt at root

    Args:
        paths (list): List of file paths to include in the zip.
        output_zip (str): Name of the output zip file.

    Returns:
        str: Absolute path to the created ZIP file.
    """
    with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for path in paths:
            p = Path(path)
            if not p.exists():
                print(f"Skipping (not found): {p}")
                continue

            # Determine target path inside ZIP
            lower_path = str(p).lower()
            if "images" in lower_path and "page_" in p.name and "figure_" in p.name:
                arcname = Path("extracted_figures") / p.name
            elif "handwritten_images" in lower_path and "page_" in p.name and "handwriting_" in p.name:
                arcname = Path("handwritten_text_images") / p.name
            elif "annotated_images" in lower_path:
                arcname = Path("annotated_images") / p.name
            elif p.name == "ocr.txt":
                arcname = "extracted_text.txt"
            else:
                # Fallback: put at root with original filename
                arcname = p.name

            zipf.write(p, arcname)

    return str(Path(output_zip).absolute())