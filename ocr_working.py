import os
import subprocess
import time
import re
import json
from pathlib import Path
from PIL import Image


# ========================== CONFIG ==========================

# Use GPU more effectively
os.environ["RECOGNITION_BATCH_SIZE"] = "512"

INPUT_PDF = "6-Page 1857 Essay from economics and political weekly.pdf"
SURYA_ENV = "ocr-llm-surya"  # Optional if using conda run
TASK_NAME = "ocr_with_boxes"
OUTPUT_BASE = "./ocr_output"

# ====================== UTILITY FUNCTIONS ======================

def get_pdf_name(file_path):
    """Extract filename (without .pdf) from full path"""
    return Path(file_path).stem

def extract_page_num(filename):
    """Get numeric page index from filename like *_5_text.png"""
    match = re.search(r"_(\d+)_text\.png$", filename)
    return int(match.group(1)) if match else -1

def get_inner_output_folder(base_output, pdf_name):
    """Surya creates nested folder: output/pdf_name/pdf_name"""
    return os.path.join(base_output, pdf_name, pdf_name)

# ======================== OCR FUNCTION =========================

def run_surya_ocr(pdf_path, output_dir):
    """Run Surya-OCR on input PDF"""
    print("🔍 Running Surya-OCR...")
    cmd = [
        "surya_ocr", pdf_path,
        "--task_name", TASK_NAME,
        "--images",
        "--output_dir", output_dir,
        "--disable_math"
    ]
    subprocess.run(cmd, check=True)
    print("✅ OCR complete.\n")

# =================== PDF & TEXT GENERATORS ===================

def images_to_pdf(images_folder, output_pdf_path):
    """Convert OCR PNGs to a single PDF"""
    print("📄 Converting images to PDF...")

    if not os.path.exists(images_folder):
        raise FileNotFoundError(f"❌ Folder not found: {images_folder}")

    images = []
    for file in sorted(os.listdir(images_folder), key=extract_page_num):
        if file.endswith("_text.png"):
            img_path = os.path.join(images_folder, file)
            img = Image.open(img_path).convert("RGB")
            images.append(img)

    if images:
        images[0].save(output_pdf_path, save_all=True, append_images=images[1:])
        print(f"✅ PDF saved to: {output_pdf_path}")
    else:
        print("❌ No images found for PDF generation.")

def extract_text_to_txt(results_json_path, output_txt_path, pdf_name):
    """Extract text from Surya's JSON into a structured TXT"""
    print("📝 Extracting text to TXT...")

    if not os.path.exists(results_json_path):
        raise FileNotFoundError(f"❌ results.json not found: {results_json_path}")

    with open(results_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    pagewise_output = []

    for idx, page_data in enumerate(data.get(pdf_name, [])):
        page_number = idx + 1
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

# ============================ MAIN ============================

def main():
    start_time = time.time()
    pdf_name = get_pdf_name(INPUT_PDF)
    output_dir = os.path.join(OUTPUT_BASE, pdf_name)
    images_folder = get_inner_output_folder(OUTPUT_BASE, pdf_name)
    results_json_path = os.path.join(images_folder, "results.json")
    output_pdf_path = os.path.join(output_dir, f"{pdf_name}_OCR.pdf")
    output_txt_path = os.path.join(output_dir, f"{pdf_name}_OCR.txt")

    os.makedirs(output_dir, exist_ok=True)

    run_surya_ocr(INPUT_PDF, output_dir)
    images_to_pdf(images_folder, output_pdf_path)
    extract_text_to_txt(results_json_path, output_txt_path, pdf_name)

    print(f"\n🎉 All done in {round(time.time() - start_time, 2)} seconds.")

# =============================================================

if __name__ == "__main__":
    main()
