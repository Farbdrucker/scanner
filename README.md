# scanme

A local-first document inbox that automatically classifies, OCRs, and renames uploaded files using a local LLM via Ollama — no cloud services required.

Upload a PDF or photo of a document and scanme will:

1. Extract text (native PDF text or Tesseract OCR for scanned documents and images)
2. Apply perspective correction to phone photos of documents
3. Classify the document with a local LLM to extract the date, descriptive tags, and payment due dates
4. Rename and store the file as `YYYY-MM-DD_tag1-tag2.ext` (e.g. `2024-02-27_invoice-acme.pdf`)
5. Save a companion `.md` file with the extracted text alongside the document

All documents are browsable, searchable, and editable through a minimal web UI.

## Features

- **Automatic classification** — date, tags, and payment due date extracted by LLM
- **OCR pipeline** — Tesseract with auto-rotation for scanned PDFs and images
- **Perspective correction** — straightens photos taken at an angle
- **Payment tracking** — due date urgency indicator (overdue / urgent / soon / future), mark as paid
- **Async processing** — uploads return immediately; LLM runs in a background queue
- **Search** — full-text search across tags, extracted text, and filenames; filter by month
- **Inline editing** — correct tags, dates, due dates, and filenames in the UI
- **Filesystem backfill** — files dropped directly into `docs/` are auto-imported on startup
- **Zero JS** — frontend built with HTMX and Jinja2 templates

## Requirements

### Local setup

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (package manager)
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) (`tesseract` binary on `PATH`)
- [Ollama](https://ollama.com/) running locally with the required model pulled

```bash
ollama pull llama3.2
```

### Docker setup

- Docker + Docker Compose
- Ollama running on the host with `llama3.2` pulled

## Installation

### Local

```bash
# Clone the repo
git clone <repo-url>
cd scanme

# Install dependencies
uv sync
```

Install Tesseract for your platform:

```bash
# macOS
brew install tesseract

# Debian / Ubuntu
sudo apt install tesseract-ocr

# Additional language data (e.g. German)
sudo apt install tesseract-ocr-deu      # Debian/Ubuntu
brew install tesseract-lang             # macOS (all languages)
```

### Docker

```bash
docker compose up --build
```

The app will be available at `http://localhost:8000`. Documents are stored in `./docs` on the host via a bind mount.

## Running

```bash
# Development server (auto-reload)
uv run python main.py

# Production-style
uv run uvicorn main:app --host 0.0.0.0 --port 8000
```

## Configuration

All settings can be overridden via environment variables or a `.env` file in the project root.

| Variable | Default | Description |
|---|---|---|
| `DOC_DIR` | `docs` | Directory where processed documents are stored |
| `DB_PATH` | `scanme.db` | SQLite database path |
| `OLLAMA_URL` | `http://localhost:11434/v1` | Ollama API base URL |
| `TEXT_MODEL` | `llama3.2` | Ollama model used for text classification |
| `OCR_LANG` | `eng` | Tesseract language(s), e.g. `eng+deu` for English + German |
| `LOG_LEVEL` | `INFO` | Set to `DEBUG` for verbose LLM I/O logging |

Example `.env`:

```env
OLLAMA_URL=http://localhost:11434/v1
TEXT_MODEL=llama3.2
OCR_LANG=eng+deu
LOG_LEVEL=DEBUG
```

## Supported file types

| Type | Processing |
|---|---|
| PDF (with text layer) | Native text extraction via PyMuPDF |
| PDF (scanned / image-only) | Render first page → Tesseract OCR |
| JPEG, PNG, WebP, GIF | Perspective correction → Tesseract OCR |
| HEIC / HEIF | Decoded and processed like JPEG |

## Development

```bash
uv sync --extra dev        # install dev dependencies
uv run pytest              # run tests
uv run ruff check .        # lint
uv run ruff format .       # format
uv run ty check            # type check
```

## Project structure

```
scanme/
├── main.py                  # FastAPI app entry point
├── app/
│   ├── config.py            # Settings (pydantic-settings, reads .env)
│   ├── agents.py            # LLM agents and DocumentMetadata model
│   ├── pipeline.py          # Upload orchestration (classify → rename → store)
│   ├── ocr.py               # Tesseract OCR with auto-rotation
│   ├── image.py             # Perspective correction and preview generation
│   ├── pdf.py               # PDF text extraction and first-page render
│   ├── storage.py           # File naming and storage
│   ├── db.py                # SQLite async database layer
│   ├── jobs.py              # Async background job queue
│   └── routes/
│       ├── pages.py         # GET / and /files (document listing + search)
│       ├── upload.py        # POST /upload
│       └── document.py      # Document detail, edit, and file serving
├── templates/               # Jinja2 HTML templates (HTMX)
├── static/                  # CSS
├── docs/                    # Stored documents (created on first run)
├── Dockerfile
└── docker-compose.yml
```

## Tech stack

- **FastAPI** + **uvicorn** — HTTP API layer
- **pydantic-ai** — LLM agent integration with Ollama
- **PyMuPDF (fitz)** — PDF text extraction and rendering
- **Tesseract** + **OpenCV** — OCR and image processing
- **aiosqlite** — async SQLite for document metadata
- **Jinja2** + **HTMX** — server-rendered UI with no custom JavaScript
- **pydantic-settings** — typed configuration from environment / `.env`
