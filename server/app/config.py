from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    doc_dir: Path = Path("docs")
    db_path: Path = Path("scanme.db")
    ollama_url: str = "http://localhost:11434/v1"
    text_model: str = "llama3.2"
    vision_model: str = "llama3.2-vision"  # unused by pipeline; kept for agents.py
    ocr_lang: str = "eng"  # e.g. "eng+deu"; override via OCR_LANG=

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
