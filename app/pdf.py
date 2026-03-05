from pathlib import Path

import fitz  # PyMuPDF


def extract_text(pdf_path: Path) -> str | None:
    """Return extracted text, or None if the PDF appears scanned (avg < 50 chars/page)."""
    doc = fitz.open(str(pdf_path))
    pages = len(doc)
    if pages == 0:
        return None
    total_chars = sum(len(page.get_text()) for page in doc)
    if total_chars / pages < 50:
        return None
    return "\n\n".join(page.get_text() for page in doc).strip() or None


def render_first_page(pdf_path: Path, dpi: int = 150) -> bytes:
    """Render first page as PNG bytes."""
    doc = fitz.open(str(pdf_path))
    page = doc[0]
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat)
    return pix.tobytes("png")


def images_to_pdf(image_bytes_list: list[bytes]) -> bytes:
    """Combine a list of images into a single PDF, one image per page."""
    doc = fitz.open()
    for img_bytes in image_bytes_list:
        pix = fitz.Pixmap(img_bytes)
        if pix.alpha:
            pix = fitz.Pixmap(fitz.csRGB, pix)
        page = doc.new_page(width=pix.width, height=pix.height)
        page.insert_image(page.rect, pixmap=pix)
    return doc.tobytes()
