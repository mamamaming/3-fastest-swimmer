# Chat with Qwen

A local Flask chat app using Ollama's `qwen3:1.7b` model. The document collection extracts and indexes PDF, DOCX, TXT, and Markdown uploads locally. Chat retrieves the five most similar text chunks and includes them as context, and reports those exact chunks as sources beneath each answer. The model receives a filename and chunk-count inventory for the full collection. For current or external information, Qwen can call Ollama web search up to five times before it returns an answer.

## Requirements

- Python 3.9 or newer
- [Ollama](https://ollama.com/) installed and running locally
- Ollama models `qwen3:1.7b` and `nomic-embed-text`
- An Ollama API key in the `OLLAMA_API_KEY` environment variable for web search

## Setup and run

```sh
ollama pull qwen3:1.7b
ollama pull nomic-embed-text
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# Set OLLAMA_API_KEY in this shell before starting Flask; do not put the key in a file.
python app.py
```

Open <http://127.0.0.1:5000>. Flask binds only to `127.0.0.1`. Individual uploads are limited to 50 MB. Uploaded files persist in `uploads/`; chunk text, source names, PDF page numbers, and embeddings persist in `data/chunks.json`. Both directories are created automatically. Chat does not read unsupported or unindexed legacy files.

## Pages

- **Chat** (`/`): sends the browser-held conversation and retrieved document context to local Ollama. Current or external questions can invoke the hosted Ollama web search API; the key is read from the process environment and is not stored by the app.
- **Document collection** (`/documents`): upload, list, and delete PDF, DOCX, TXT, and Markdown files. Each file is indexed with Ollama's local embedding API. Deleting a file also removes its indexed chunks.
