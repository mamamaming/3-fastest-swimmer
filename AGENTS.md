# Repository Guidelines

## Project Structure

- `app.py` contains Flask page routes and JSON APIs.
- `templates/` contains the chat and document collection pages.
- `static/` contains page-specific JavaScript and shared CSS.
- `uploads/` is created at runtime and holds document files; do not commit its contents.

## Development

Create a virtual environment, install dependencies, and start the local server:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

The server must remain bound to `127.0.0.1`. Ollama chat uses the local `qwen3:1.7b` model and `nomic-embed-text` for document retrieval. Web search reads `OLLAMA_API_KEY` from the process environment; never commit or write the key to a file. Document uploads and indexes are stored locally.

## Style and Testing

Keep Python routes and file handling in `app.py`, use semantic HTML templates, and keep browser behavior in the relevant file under `static/`. Avoid adding dependencies for functionality available in Python or browser APIs. There is no test suite currently; when adding one, document its run command here and in the README.

## Changes

Use short, imperative commit subjects. Pull requests should describe user-visible behavior, note validation performed, and include screenshots when they clarify UI changes. Never commit credentials, virtual environments, or uploaded user files.
