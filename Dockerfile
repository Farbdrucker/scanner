FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock ./

# Install runtime dependencies only (no dev extras)
RUN uv sync --no-dev --frozen

# Copy application code
COPY . .

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "main:app", "--app-dir", "server", "--host", "0.0.0.0", "--port", "8000"]
