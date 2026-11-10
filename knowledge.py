"""Knowledge base: reading files, splitting them into chunks, search, club facts. Owner: Boom."""

import json
import math
import threading
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile

from docx import Document
from pypdf import PdfReader

from config import (
    CHUNK_OVERLAP, CHUNK_SIZE, CLUB_FACTS_PATH, DATA_FOLDER, EMBED_MODEL, INDEX_PATH,
    OLLAMA_EMBED_URL, RETRIEVAL_COUNT, UPLOAD_FOLDER,
)
from ollama_client import OllamaError, ollama_post

INDEX_LOCK = threading.Lock()


def embed_texts(texts):
    """Create embeddings in modest batches to avoid oversized API requests."""
    vectors = []
    batch_size = 32
    for offset in range(0, len(texts), batch_size):
        response = ollama_post(
            OLLAMA_EMBED_URL,
            {"model": EMBED_MODEL, "input": texts[offset:offset + batch_size]},
            timeout=300,
        )
        batch = response.get("embeddings") if isinstance(response, dict) else None
        if not isinstance(batch, list) or len(batch) != len(texts[offset:offset + batch_size]):
            raise OllamaError(
                f"Ollama did not return embeddings. Ensure the {EMBED_MODEL} model is available."
            )
        for vector in batch:
            if not isinstance(vector, list) or not vector or not all(
                isinstance(value, (int, float)) and math.isfinite(value) for value in vector
            ):
                raise OllamaError("Ollama returned an invalid embedding.")
            vectors.append(vector)
    return vectors


def extract_document(filename, content):
    extension = Path(filename).suffix.lower()
    if extension == ".pdf":
        reader = PdfReader(BytesIO(content))
        pages = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                pages.append((page_number, text))
    elif extension == ".docx":
        document = Document(BytesIO(content))
        lines = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
        for table in document.tables:
            for row in table.rows:
                lines.append(" | ".join(cell.text for cell in row.cells))
        pages = [(None, "\n".join(lines))]
    else:
        try:
            pages = [(None, content.decode("utf-8-sig"))]
        except UnicodeDecodeError as error:
            raise ValueError("This text file is not valid UTF-8 encoded text.") from error

    if not any(text.strip() for _, text in pages):
        raise ValueError("No readable text was found in this file. Scanned PDFs need OCR before upload.")
    return pages


def split_text(text, page_number=None):
    text = " ".join(text.split())
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        if end < len(text):
            boundary = text.rfind(" ", start + CHUNK_SIZE // 2, end)
            if boundary > start:
                end = boundary
        chunk = text[start:end].strip()
        if chunk:
            chunks.append({"page": page_number, "text": chunk})
        if end >= len(text):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


def load_index():
    if not INDEX_PATH.exists():
        return []
    with INDEX_PATH.open("r", encoding="utf-8") as source:
        data = json.load(source)
    if not isinstance(data, list):
        raise ValueError("The local document index is not a valid list.")
    source_chunk_counts = {}
    for chunk in data:
        source = chunk.get("source", "")
        source_chunk_counts[source] = source_chunk_counts.get(source, 0) + 1
        chunk.setdefault("chunk", source_chunk_counts[source])
    return data


def save_index(chunks):
    DATA_FOLDER.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=DATA_FOLDER, delete=False) as temporary:
        json.dump(chunks, temporary, ensure_ascii=False)
        temporary_path = Path(temporary.name)
    temporary_path.replace(INDEX_PATH)


def cosine_similarity(left, right):
    if len(left) != len(right):
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


def retrieve_context(question):
    with INDEX_LOCK:
        chunks = load_index()
    if not chunks:
        return []
    question_vector = embed_texts([question])[0]
    ranked = sorted(
        ((cosine_similarity(question_vector, item["embedding"]), item) for item in chunks),
        key=lambda pair: pair[0],
        reverse=True,
    )
    return [item for score, item in ranked[:RETRIEVAL_COUNT] if score > 0]


def document_records():
    with INDEX_LOCK:
        chunks = load_index()
    counts = {}
    for chunk in chunks:
        counts[chunk["source"]] = counts.get(chunk["source"], 0) + 1
    files = []
    for path in UPLOAD_FOLDER.iterdir():
        if path.is_file():
            count = counts.get(path.name, 0)
            files.append({"name": path.name, "size": path.stat().st_size, "chunks": count})
    return sorted(files, key=lambda item: item["name"].lower())


def search_sections(section, event_type, query, k=3):
    """Return the k chunks most similar to query whose section matches (A3)."""
    raise NotImplementedError("search_sections is task A3 (Boom). See docs/SPEC.md.")


def load_club_facts(path=CLUB_FACTS_PATH):
    """Read club-facts.md into a dict (A4)."""
    raise NotImplementedError("load_club_facts is task A4 (Boom). See docs/SPEC.md.")
