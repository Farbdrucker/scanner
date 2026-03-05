
import fitz

from app.pdf import extract_text, images_to_pdf, render_first_page


def _make_text_pdf(text: str) -> bytes:
    """Create a minimal single-page PDF with selectable text."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 72), text)
    return doc.tobytes()


def _make_blank_pdf() -> bytes:
    """Create a minimal single-page PDF with no text."""
    doc = fitz.open()
    doc.new_page()
    return doc.tobytes()


def test_extract_text_returns_text(tmp_path):
    content = "Invoice 2024-01-15\n" + "A" * 200  # well above 50 chars/page
    pdf_bytes = _make_text_pdf(content)
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(pdf_bytes)

    result = extract_text(pdf_path)
    assert result is not None
    assert "Invoice" in result


def test_extract_text_returns_none_for_blank(tmp_path):
    pdf_path = tmp_path / "blank.pdf"
    pdf_path.write_bytes(_make_blank_pdf())

    assert extract_text(pdf_path) is None


def test_render_first_page_returns_png(tmp_path):
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(_make_text_pdf("Hello"))

    png_bytes = render_first_page(pdf_path)
    assert png_bytes[:4] == b"\x89PNG"


def _make_png() -> bytes:
    """Create a small PNG via fitz (blank page rendered to PNG)."""
    doc = fitz.open()
    page = doc.new_page(width=100, height=100)
    pix = page.get_pixmap()
    return pix.tobytes("png")


def test_images_to_pdf_single_page():
    pdf_bytes = images_to_pdf([_make_png()])
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    assert len(doc) == 1


def test_images_to_pdf_multiple_pages():
    pdf_bytes = images_to_pdf([_make_png(), _make_png(), _make_png()])
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    assert len(doc) == 3


def test_images_to_pdf_page_dimensions():
    pdf_bytes = images_to_pdf([_make_png()])
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[0]
    assert page.rect.width == 100
    assert page.rect.height == 100
