import re
import shutil
from datetime import datetime
from pathlib import Path

from app.config import settings


def build_filename(date: str, tags: list[str], ext: str) -> str:
    """Build filename like 2024-01-15_invoice-acme.pdf"""
    safe_tags = [
        re.sub(r"[^a-z0-9-]", "", re.sub(r"[\s_]+", "-", t.lower())) for t in tags
    ]
    safe_tags = [t for t in safe_tags if t][:5]
    tag_str = "-".join(safe_tags) if safe_tags else "document"
    clean_ext = ext.lstrip(".")
    return f"{date}_{tag_str}.{clean_ext}"


def fallback_filename(ext: str) -> str:
    """Timestamp-based fallback when LLM output is unusable."""
    ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    clean_ext = ext.lstrip(".")
    return f"{ts}_document.{clean_ext}"


def resolve_collision(dest_dir: Path, filename: str) -> Path:
    """Append _1, _2, ... until a free name is found."""
    candidate = dest_dir / filename
    if not candidate.exists():
        return candidate
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 1
    while True:
        candidate = dest_dir / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def store_file(tmp_path: Path, filename: str) -> Path:
    """Move tmp_path into doc_dir under the given filename."""
    dest_dir = settings.doc_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = resolve_collision(dest_dir, filename)
    shutil.move(str(tmp_path), dest)
    return dest


def store_markdown(doc_path: Path, content: str) -> Path:
    """Write extracted text as a .md companion file next to doc_path."""
    md_path = doc_path.with_suffix(".md")
    md_path.write_text(f"# {doc_path.name}\n\n{content}\n", encoding="utf-8")
    return md_path
