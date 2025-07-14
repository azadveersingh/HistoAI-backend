import fitz  # PyMuPDF
from typing import List, Tuple
from stanza import Pipeline
from ..extensions import socketio  # Adjust if needed

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


def process_and_get_chunks(file_path: str, unique_folder: str, filename: str) -> List[Tuple[int, str, str]]:
    """
    Processes the entire PDF as a whole and returns chunks (chunk_id, chunk_text, source_url).
    """
    try:
        full_text = extract_full_text(file_path)
        chunks = stanza_chunker(full_text)

        chunk_results = []
        for idx, chunk in enumerate(chunks, start=1):
            source_url = f"{unique_folder}/{filename}#page={idx}"
            chunk_results.append((idx, chunk, source_url))

        socketio.emit("completed", {"message": "Chunk extraction completed successfully!"})
        return chunk_results

    except Exception as e:
        print(f"❌ Error: {e}")
        return []
