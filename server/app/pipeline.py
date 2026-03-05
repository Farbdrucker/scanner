import tempfile
from datetime import date as _date
from pathlib import Path

from app.agents import classify_text
from app.db import insert_document
from app.image import correct_perspective, make_preview
from app.ocr import extract_text_from_image
from app.pdf import extract_text, render_first_page
from app.storage import build_filename, fallback_filename, store_file, store_markdown

_IMAGE_TYPES = {
    "image/jpeg": "image/jpeg",
    "image/jpg": "image/jpeg",
    "image/png": "image/png",
    "image/gif": "image/gif",
    "image/webp": "image/webp",
    "image/heic": "image/jpeg",
    "image/heif": "image/jpeg",
}


async def process_upload(
    file_bytes: bytes, original_filename: str
) -> tuple[Path, str, str]:
    """
    Classify and store an uploaded file.

    Returns (stored_path, final_filename, preview_b64).
    """
    ext = Path(original_filename).suffix.lower() or ".bin"
    content_type = _guess_media_type(original_filename)

    tmp_path: Path | None = None
    try:
        # Write to a named temp file so pdf.py can open it with fitz
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as f:
            f.write(file_bytes)
            tmp_path = Path(f.name)

        _doc_date: str = _date.today().isoformat()
        _doc_tags: list[str] = []
        _extracted_text: str = ""
        _is_fallback: bool = True
        ocr_text: str = ""
        preview_b64: str = ""
        try:
            if content_type == "application/pdf":
                text = extract_text(tmp_path)
                if text:
                    _extracted_text = text
                    metadata = await classify_text(text)
                else:
                    png_bytes = render_first_page(tmp_path)
                    ocr_text = extract_text_from_image(png_bytes) or ""
                    if not ocr_text:
                        raise ValueError("OCR produced no text for scanned PDF")
                    _extracted_text = ocr_text
                    metadata = await classify_text(ocr_text)
            elif content_type in _IMAGE_TYPES:
                corrected = correct_perspective(file_bytes)
                preview_b64 = make_preview(corrected)
                ocr_text = extract_text_from_image(corrected) or ""
                if not ocr_text:
                    raise ValueError("OCR produced no text for image")
                _extracted_text = ocr_text
                metadata = await classify_text(ocr_text)
            else:
                corrected = correct_perspective(file_bytes)
                preview_b64 = make_preview(corrected)
                ocr_text = extract_text_from_image(corrected) or ""
                if not ocr_text:
                    raise ValueError("OCR produced no text for unknown type")
                _extracted_text = ocr_text
                metadata = await classify_text(ocr_text)

            _doc_date = metadata.date
            _doc_tags = metadata.tags
            _doc_due_date: str | None = metadata.due_date
            _is_fallback = False
            filename = build_filename(metadata.date, metadata.tags, ext)
        except Exception:
            filename = fallback_filename(ext)
            _doc_due_date = None
            ocr_text = ""  # never write markdown on the fallback path

        stored = store_file(tmp_path, filename)
        tmp_path = None  # ownership transferred — don't delete
        if ocr_text:
            store_markdown(stored, ocr_text)

        await insert_document(
            stored_filename=stored.name,
            original_filename=original_filename,
            date=_doc_date,
            tags=_doc_tags,
            extracted_text=_extracted_text,
            file_size=stored.stat().st_size,
            content_type=content_type,
            is_fallback=_is_fallback,
            due_date=_doc_due_date,
        )
        return stored, filename, preview_b64

    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def _guess_media_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return {
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".heic": "image/heic",
        ".heif": "image/heif",
    }.get(ext, "application/octet-stream")
