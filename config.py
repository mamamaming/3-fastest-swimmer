"""Shared settings. Owner: Ming."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = BASE_DIR / "uploads"
DATA_FOLDER = BASE_DIR / "data"
INDEX_PATH = DATA_FOLDER / "chunks.json"
BRIEFS_FOLDER = DATA_FOLDER / "briefs"
SAMPLES_FOLDER = BASE_DIR / "samples"
CLUB_FACTS_PATH = UPLOAD_FOLDER / "club-facts.md"

MAX_FILE_SIZE = 50 * 1024 * 1024
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}

OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"
OLLAMA_EMBED_URL = "http://localhost:11434/api/embed"
OLLAMA_WEB_SEARCH_URL = "https://ollama.com/api/web_search"
MODEL = "qwen3:1.7b"  # Yuay picks the proposal model in B2; change it here.
EMBED_MODEL = "nomic-embed-text"
OLLAMA_CHAT_TIMEOUT = 600

CHUNK_SIZE = 900
CHUNK_OVERLAP = 100
RETRIEVAL_COUNT = 5
MAX_WEB_SEARCH_CALLS = 5

UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
DATA_FOLDER.mkdir(parents=True, exist_ok=True)
