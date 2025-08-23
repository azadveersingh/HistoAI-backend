import os
import time
import re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from surya.layout import LayoutPredictor
from surya.recognition import RecognitionPredictor
from surya.detection import DetectionPredictor
from pdf2image import convert_from_path
import random
from datetime import datetime, timezone
from ..extensions import mongo, socketio
from ..models import ocr_model
from ..config import Config
from ..helpers.file_helpers import create_book_folder_structure
import shutil 

# ========================== CONFIG ==========================

os.environ["LAYOUT_BATCH_SIZE"] = "32"
os.environ["RECOGNITION_BATCH_SIZE"] = "512"
os.environ["DETECTOR_BATCH_SIZE"] = "36"

MIN_AREA = 1500
MIN_CONFIDENCE = 0.48
MIN_ASPECT_RATIO = 0.3
MAX_ASPECT_RATIO = 3.0
TEXT_CONFIDENCE = 0.7
PAGE_HEADER_CONFIDENCE = 0.7
SECTION_HEADER_CONFIDENCE = 0.7
MIN_TEXT_LENGTH = 3
Y_THRESHOLD = 20
MIN_BBOX_HEIGHT = 160
MIN_BBOX_WIDTH = 200

# Color map for layout elements (moved to module level)
COLOR_MAP = {
    "SectionHeader": "red",
    "Text": "blue",
    "Table": "green",
    "Figure": "purple",
    "Picture": "purple",
    "PageHeader": "orange",
    "Footnote": "cyan",
    "Handwriting": "yellow"
}

# ====================== UTILITY FUNCTIONS ======================

def get_pdf_name(file_path):
    """Extract filename (without .pdf) from full path"""
    return Path(file_path).stem

def get_color(label):
    """Return color for layout element"""
    return COLOR_MAP.get(label, (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)))

def is_valid_figure_box(bbox, confidence, image_size):
    """Check if a bounding box is valid for figures or handwritten text"""
    x1, y1, x2, y2 = bbox
    width = x2 - x1
    height = y2 - y1
    area = width * height
    aspect_ratio = width / height if height > 0 else float('inf')
    img_width, img_height = image_size
    is_valid = (area > MIN_AREA and 
                MIN_ASPECT_RATIO <= aspect_ratio <= MAX_ASPECT_RATIO and
                confidence > MIN_CONFIDENCE and 
                x2 <= img_width and y2 <= img_height and
                width >= MIN_BBOX_WIDTH and 
                height >= MIN_BBOX_HEIGHT)
    return is_valid, aspect_ratio

def is_overlapping(bbox1, bbox2):
    """Check if two bounding boxes overlap"""
    x1_1, y1_1, x2_1, y2_1 = bbox1
    x1_2, y1_2, x2_2, y2_2 = bbox2
    return not (x2_1 < x1_2 or x2_2 < x1_1 or y2_1 < y1_2 or y2_2 < y1_1)

def group_into_rows(text_lines, y_threshold=Y_THRESHOLD):
    """Group text lines into rows based on y-coordinates"""
    if not text_lines:
        return []
    sorted_lines = sorted(text_lines, key=lambda x: x.bbox[1])
    rows = []
    current_row = [sorted_lines[0]]
    current_y = sorted_lines[0].bbox[1]
    
    for line in sorted_lines[1:]:
        y1 = line.bbox[1]
        if abs(y1 - current_y) <= y_threshold:
            current_row.append(line)
        else:
            rows.append(current_row)
            current_row = [line]
            current_y = y1
    if current_row:
        rows.append(current_row)
    
    for row in rows:
        row.sort(key=lambda x: x.bbox[0])
    return rows

def format_table_html(rows):
    """Format table rows as HTML"""
    if not rows:
        return "<table></table>"
    html = "<table border='1'>\n"
    for row in rows:
        html += "  <tr>\n"
        for cell in row:
            html += f"    <td>{cell.text}</td>\n"
        html += "  </tr>\n"
    html += "</table>\n"
    return html

# ======================== OCR FUNCTION =========================

def run_surya_ocr(pdf_path, book_id):
    """Run Surya OCR with layout and text recognition"""
    print("🔍 Running Surya-OCR...")
    socketio.emit("book_progress", {
        "book_id": book_id,
        "status": "start_ocr_processing",
        "message": f"Starting OCR processing for {os.path.basename(pdf_path)}"
    })
    
    try:
        # Convert PDF to images
        images = convert_from_path(pdf_path)
        socketio.emit("book_progress", {
            "book_id": book_id,
            "status": "pdf_converted",
            "message": f"Converted PDF to {len(images)} images"
        })
        
        # Initialize predictors
        layout_pred = LayoutPredictor()
        rec_pred = RecognitionPredictor()
        det_pred = DetectionPredictor()
        
        # Process images
        layout_results = layout_pred(images)
        text_results = rec_pred(images, det_predictor=det_pred)
        
        print("✅ OCR complete.")
        socketio.emit("book_progress", {
            "book_id": book_id,
            "status": "ocr_done",
            "message": f"OCR completed for {os.path.basename(pdf_path)}"
        })
        return True, images, layout_results, text_results, None
    except Exception as e:
        error_msg = f"Surya-OCR failed: {str(e)}"
        print(f"❌ {error_msg}")
        socketio.emit("book_progress", {
            "book_id": book_id,
            "status": "error",
            "message": f"OCR failed for {os.path.basename(pdf_path)}: {error_msg}"
        })
        return False, None, None, None, error_msg

# =================== TEXT AND IMAGE EXTRACTOR ===================

def extract_content(images, layout_results, text_results, output_txt_path, fig_dir, annotated_dir, handwritten_dir, pdf_name, book_id):
    """Extract text, figures, handwritten text, and create annotated images"""
    print("📝 Extracting content...")
    socketio.emit("book_progress", {
        "book_id": book_id,
        "status": "processing",
        "message": f"Extracting content for {pdf_name}",
        "progress": 50
    })

    total_pages = len(images)
    socketio.emit("book_progress", {
        "book_id": book_id,
        "status": "total_pages",
        "message": f"Book {pdf_name} has {total_pages} pages",
        "total_pages": total_pages
    })

    with open(output_txt_path, 'w', encoding='utf-8') as text_file:
        for i, (image, layout_result, text_result) in enumerate(zip(images, layout_results, text_results)):
            page_number = i + 1
            progress_percent = round((page_number / total_pages) * 100, 2)
            print(f"➡️ Processing page {page_number}/{total_pages} ({progress_percent}%)")
            socketio.emit("book_progress", {
                "book_id": book_id,
                "status": "processing",
                "message": f"Processing page {page_number}/{total_pages} for {pdf_name}",
                "progress": progress_percent
            })

            # Get regions
            figure_regions = [box.bbox for box in layout_result.bboxes if box.label in ["Figure", "Picture"] and
                             is_valid_figure_box(box.bbox, box.confidence, image.size)[0]]
            table_regions = [box.bbox for box in layout_result.bboxes if box.label == "Table"]
            handwriting_regions = [box.bbox for box in layout_result.bboxes if box.label == "Handwriting" and
                                 is_valid_figure_box(box.bbox, box.confidence, image.size)[0]]
            
            # Extract headers
            page_headers = [box for box in layout_result.bboxes if box.label == "PageHeader" and box.confidence > PAGE_HEADER_CONFIDENCE]
            section_headers = [box for box in layout_result.bboxes if box.label == "SectionHeader" and box.confidence > SECTION_HEADER_CONFIDENCE]
            
            text_file.write(f"\n<----- Page {page_number} ----->\n")
            text_file.write("Page Headers:\n")
            if page_headers:
                for header in page_headers:
                    header_text = next((line.text for line in text_result.text_lines if is_overlapping(line.bbox, header.bbox)), "Unknown")
                    overlaps = any(is_overlapping(header.bbox, region) for region in figure_regions + table_regions + handwriting_regions)
                    if not overlaps:
                        text_file.write(f"- {header_text} (confidence={header.confidence:.2f})\n")
            else:
                text_file.write("- None\n")
            
            text_file.write("\nSection Headers:\n")
            if section_headers:
                for header in section_headers:
                    header_text = next((line.text for line in text_result.text_lines if is_overlapping(line.bbox, header.bbox)), "Unknown")
                    overlaps = any(is_overlapping(header.bbox, region) for region in figure_regions + table_regions + handwriting_regions)
                    if not overlaps:
                        text_file.write(f"- {header_text} (confidence={header.confidence:.2f})\n")
            else:
                text_file.write("- None\n")
            
            # Extract text
            text_file.write("\nText:\n")
            text_written = False
            for text_line in text_result.text_lines:
                text = text_line.text
                text_bbox = text_line.bbox
                overlaps = any(is_overlapping(text_bbox, region) for region in figure_regions + table_regions + handwriting_regions)
                if (not overlaps and
                    text_line.confidence > TEXT_CONFIDENCE and 
                    len(text) > MIN_TEXT_LENGTH and 
                    "ext" not in text.lower() and 
                    "<math" not in text.lower() and 
                    "<b" not in text.lower() and 
                    not (len(text) > 10 and sum(c.isdigit() for c in text) > len(text) * 0.8)):
                    text_file.write(f"{text}\n")
                    text_written = True
            if not text_written:
                text_file.write("- None\n")
            
            # Extract tables
            text_file.write("\nTables:\n")
            table_idx = 1
            for table_bbox in table_regions:
                table_lines = [line for line in text_result.text_lines if is_overlapping(line.bbox, table_bbox)]
                rows = group_into_rows(table_lines)
                table_html = format_table_html(rows)
                text_file.write(f"Table {table_idx}:\n{table_html}\n")
                table_idx += 1
            if table_idx == 1:
                text_file.write("- None\n")
            
            # Extract figures and handwritten text
            figure_paths = []
            handwriting_paths = []
            figure_idx = 1
            handwriting_idx = 1
            img_copy = image.copy()
            draw = ImageDraw.Draw(img_copy)
            try:
                font = ImageFont.truetype("arial.ttf", 20)
            except:
                font = ImageFont.load_default()
            
            for box in layout_result.bboxes:
                int_polygon = [(int(x), int(y)) for x, y in box.polygon]
                color = get_color(box.label)
                draw.polygon(int_polygon, outline=color, width=3)
                is_valid, aspect_ratio = is_valid_figure_box(box.bbox, box.confidence, image.size)
                label_text = f"{box.label} ({box.confidence:.2f}, AR={aspect_ratio:.2f})" if is_valid else f"{box.label} ({box.confidence:.2f})"
                draw.text((int_polygon[0][0], int_polygon[0][1]), label_text, fill=color, font=font)
                
                if box.label in ["Figure", "Picture"] and is_valid:
                    bbox = box.bbox
                    cropped_image = image.crop((bbox[0], bbox[1], bbox[2], bbox[3]))
                    figure_path = os.path.join(fig_dir, f"page_{page_number}_figure_{figure_idx}.png")
                    cropped_image.save(figure_path)
                    if figure_path not in figure_paths:
                        figure_paths.append(figure_path)
                    figure_idx += 1
                
                if box.label == "Handwriting" and is_valid:
                    bbox = box.bbox
                    cropped_image = image.crop((bbox[0], bbox[1], bbox[2], bbox[3]))
                    handwriting_path = os.path.join(handwritten_dir, f"page_{page_number}_handwriting_{handwriting_idx}.png")
                    cropped_image.save(handwriting_path)
                    if handwriting_path not in handwriting_paths:
                        handwriting_paths.append(handwriting_path)
                    handwriting_idx += 1
            
            text_file.write(f"\nExtracted Images (Page {page_number}):\n")
            if figure_paths:
                for path in figure_paths:
                    relative_path = os.path.join("OCR Text & Images", "images", os.path.basename(path))
                    text_file.write(f"- {relative_path}\n")
            else:
                text_file.write("- None\n")
            
            text_file.write(f"\nExtracted Handwritten Text Images (Page {page_number}):\n")
            if handwriting_paths:
                for path in handwriting_paths:
                    relative_path = os.path.join("OCR Text & Images", "handwritten_images", os.path.basename(path))
                    text_file.write(f"- {relative_path}\n")
            else:
                text_file.write("- None\n")
            
            annotated_path = os.path.join(annotated_dir, f"page_{page_number}_annotated.png")
            img_copy.save(annotated_path)
    
    # Create legend image
    legend_img = Image.new("RGB", (400, 200), "white")
    draw = ImageDraw.Draw(legend_img)
    try:
        font = ImageFont.truetype("arial.ttf", 20)
    except:
        font = ImageFont.load_default()
    draw.text((10, 10), "Layout Element Colors:", fill="black", font=font)
    y_pos = 40
    for label, color in COLOR_MAP.items():
        draw.rectangle([10, y_pos, 30, y_pos+20], fill=color, outline="black")
        draw.text((40, y_pos), label, fill="black", font=font)
        y_pos += 30
    legend_img.save(os.path.join(annotated_dir, "layout_legend.png"))

    print(f"✅ Content extraction completed: {output_txt_path}")
    socketio.emit("book_progress", {
        "book_id": book_id,
        "status": "content_extracted",
        "message": f"Content extraction completed for {pdf_name}",
        "progress": 100
    })

# ============================ MAIN ============================

def process_book_ocr(book_id, pdf_path):
    start_time = time.time()
    pdf_name = get_pdf_name(pdf_path)
    book_dir = create_book_folder_structure(book_id)
    ocr_dir = os.path.join(book_dir, "OCR Text & Images")
    output_txt_path = os.path.join(ocr_dir, "ocr.txt")
    fig_dir = os.path.join(ocr_dir, "images")
    annotated_dir = os.path.join(ocr_dir, "annotated_images")
    handwritten_dir = os.path.join(ocr_dir, "handwritten_images")

    try:
        os.makedirs(fig_dir, exist_ok=True)
        os.makedirs(annotated_dir, exist_ok=True)
        os.makedirs(handwritten_dir, exist_ok=True)

        ocr_process = ocr_model.get_ocr_process_by_book(mongo, book_id)
        if not ocr_process:
            socketio.emit("book_progress", {
                "book_id": book_id,
                "status": "error",
                "message": f"OCR process not found for book ID {book_id}"
            })
            return False, "OCR process not found"

        socketio.emit("book_progress", {
            "book_id": book_id,
            "status": "book_received",
            "message": f"Book {pdf_name} received for OCR processing"
        })

        ocr_model.update_ocr_process(mongo, ocr_process["_id"], {
            "status": "processing",
            "progress": 10,
            "updatedAt": datetime.now(timezone.utc)
        })

        success, images, layout_results, text_results, error_message = run_surya_ocr(pdf_path, book_id)
        if not success:
            ocr_model.update_ocr_process(mongo, ocr_process["_id"], {
                "status": "failed",
                "errorMessage": error_message,
                "progress": 0,
                "updatedAt": datetime.now(timezone.utc)
            })
            return False, error_message

        ocr_model.update_ocr_process(mongo, ocr_process["_id"], {
            "progress": 50,
            "updatedAt": datetime.now(timezone.utc)
        })

        extract_content(images, layout_results, text_results, output_txt_path, fig_dir, annotated_dir, handwritten_dir, pdf_name, book_id)

        # Remove annotated_dir after successful processing
        try:
            if os.path.exists(annotated_dir):
                shutil.rmtree(annotated_dir)
                print(f"🗑️ Removed annotated images folder: {annotated_dir}")
        except Exception as e:
            print(f"⚠️ Failed to remove annotated_dir: {e}")

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