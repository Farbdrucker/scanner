# Scanner


![Version](https://img.shields.io/badge/version-0.2.0-blue.svg)
![Tests](https://github.com/Farbdrucker/wozapftes/actions/workflows/tests.yml/badge.svg)
![CI](https://github.com/Farbdrucker/wozapftes/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.12+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-blue.svg)


A local-first document scanner that saves all documents to a single directory and analyzes them using a locally running LLM.

## Installation

First, clone the repository:

```commandline
git clone https://github.com/Farbdrucker/scanner.git
cd scanner
```

### Server Setup

Start the service using Docker Compose:

```commandline
docker compose up --build -d
```

This will start the service on port `8000`. You can update `docker-compose.yml` if you need to change the port mapping.

Verify the application is running by visiting `http://localhost:8000/` (or your specific IP/port). For more advanced configuration options, see `server/app/config.py::Settings`.

#### Ollama Configuration

Install Ollama if you haven't already:

```commandline
curl -fsSL https://ollama.com/install.sh | sh
```

Choose a model based on your hardware constraints. For a small home server, `qwen2.5:3b` is recommended:

```commandline
ollama pull qwen2.5:3b
echo "TEXT_MODEL=qwen2.5:3b" >> server/.env
```

### CLI Setup

The server must be running before you can use the CLI. Configure the CLI with your server's IP address:

```commandline
echo "SCANME_URL=http://{YOUR_IP}:8000" >> cli/.env
```

To see available commands:

```commandline
uv run scanme --help
```

## Tech Stack

* **FastAPI** + **Uvicorn** — HTTP API layer
* **Pydantic AI** — LLM agent integration with Ollama
* **PyMuPDF (fitz)** — PDF text extraction and rendering
* **Tesseract** + **OpenCV** — OCR and image processing
* **aiosqlite** — Asynchronous SQLite for document metadata
* **Jinja2** + **HTMX** — Server-rendered UI with no custom JavaScript
* **pydantic-settings** — Typed configuration management
