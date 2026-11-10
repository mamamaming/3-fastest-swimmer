# Repository Guidelines

Read `docs/SPEC.md` before any task. It describes the Proposal Writer: a local Flask + Ollama app that turns a short form into a finished BizComp activity proposal (.docx).

## Project Structure and Ownership

Three people work in this repo at the same time. Each file has one owner. Only edit the files named in your task; if another file must change, keep the change minimal and say so in your summary.

| File | Owner | Contents |
|---|---|---|
| `knowledge.py` | Boom | Text extraction, splitting by section, search, `load_club_facts()` |
| `templates/documents.html`, `static/documents.js` | Boom | Upload page |
| `writer.py`, `prompts/` | Yuay | Gap questions, per-section prompts, model calls |
| `templates/new.html`, `static/new.js` | Yuay | Proposal form page |
| `scripts/compare_models.py` | Yuay | Model comparison |
| `export.py`, `templates/proposal_template.docx` | Ming | Filling the Word template |
| `checker.py` | Ming | Consistency checks |
| `app.py`, `config.py` | Ming | Flask routes and settings only |

`app.py` holds routes only. A route should be a short function that calls a function from one of the modules above. Put logic in the modules, not in `app.py`.

All parts exchange one JSON object, the event brief (see `docs/SPEC.md`). Do not change its fields without agreement from all three owners.

## Data and Privacy

- The repository is public. Never commit real proposals, `club-facts.md`, uploaded files, `uploads/`, `data/`, or credentials.
- Use files in `samples/` (made-up data) for tests and examples.
- Uploaded files live in `uploads/`; the text index and saved briefs live in `data/`. Both are git-ignored.

## Development

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

The server must remain bound to `127.0.0.1`. Model names live in `config.py`. Proposal generation does not use web search. The model never writes budget numbers; budget arithmetic is done in code.

## Style and Testing

Use semantic HTML templates and keep browser behaviour in the page's file under `static/`. Avoid adding dependencies for functionality available in Python or browser APIs. Each task in `docs/SPEC.md` ends with a "Check" line; run it before committing.

## Changes

Use short, imperative commit subjects. Stage only the files you changed (no `git add .`). Pull before starting work.
