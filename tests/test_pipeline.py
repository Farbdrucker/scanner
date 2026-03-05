from unittest.mock import AsyncMock, patch

import fitz
import pytest
from app.agents import DocumentMetadata


def _make_text_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 72), "Invoice 2024-03-01 " + "x" * 200)
    return doc.tobytes()


def _make_blank_pdf() -> bytes:
    doc = fitz.open()
    doc.new_page()
    return doc.tobytes()


MOCK_METADATA = DocumentMetadata(date="2024-03-01", tags=["invoice", "acme"])


@pytest.mark.asyncio
async def test_pipeline_text_pdf(tmp_path):
    from app.pipeline import process_upload

    with (
        patch("app.pipeline.classify_text", new=AsyncMock(return_value=MOCK_METADATA)),
        patch("app.pipeline.store_file") as mock_store,
        patch("app.pipeline.store_markdown") as mock_md,
        patch("app.pipeline.insert_document", new=AsyncMock()),
    ):
        stored_path = tmp_path / "2024-03-01_invoice-acme.pdf"
        stored_path.write_bytes(b"fake")
        mock_store.return_value = stored_path
        stored, filename, _ = await process_upload(_make_text_pdf(), "doc.pdf")
        assert filename == "2024-03-01_invoice-acme.pdf"
        mock_md.assert_not_called()


@pytest.mark.asyncio
async def test_pipeline_scanned_pdf(tmp_path):
    from app.pipeline import process_upload

    with (
        patch(
            "app.pipeline.extract_text_from_image", return_value="Extracted OCR text."
        ),
        patch("app.pipeline.classify_text", new=AsyncMock(return_value=MOCK_METADATA)),
        patch("app.pipeline.store_file") as mock_store,
        patch("app.pipeline.store_markdown") as mock_md,
        patch("app.pipeline.insert_document", new=AsyncMock()),
    ):
        stored_path = tmp_path / "2024-03-01_invoice-acme.pdf"
        stored_path.write_bytes(b"fake")
        mock_store.return_value = stored_path
        stored, filename, _ = await process_upload(_make_blank_pdf(), "scan.pdf")
        assert filename == "2024-03-01_invoice-acme.pdf"
        mock_md.assert_called_once_with(stored_path, "Extracted OCR text.")


@pytest.mark.asyncio
async def test_pipeline_image(tmp_path):
    from app.pipeline import process_upload

    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

    with (
        patch("app.pipeline.correct_perspective", return_value=fake_png),
        patch(
            "app.pipeline.extract_text_from_image", return_value="Extracted OCR text."
        ),
        patch("app.pipeline.classify_text", new=AsyncMock(return_value=MOCK_METADATA)),
        patch("app.pipeline.store_file") as mock_store,
        patch("app.pipeline.store_markdown") as mock_md,
        patch("app.pipeline.insert_document", new=AsyncMock()),
    ):
        stored_path = tmp_path / "2024-03-01_invoice-acme.png"
        stored_path.write_bytes(b"fake")
        mock_store.return_value = stored_path
        stored, filename, _ = await process_upload(fake_png, "photo.png")
        assert filename == "2024-03-01_invoice-acme.png"
        mock_md.assert_called_once_with(stored_path, "Extracted OCR text.")


@pytest.mark.asyncio
async def test_pipeline_fallback_on_llm_error(tmp_path):
    from app.pipeline import process_upload

    with (
        patch(
            "app.pipeline.classify_text",
            new=AsyncMock(side_effect=RuntimeError("LLM down")),
        ),
        patch("app.pipeline.store_file") as mock_store,
        patch("app.pipeline.store_markdown") as mock_md,
        patch("app.pipeline.insert_document", new=AsyncMock()),
    ):
        stored_path = tmp_path / "fallback.pdf"
        stored_path.write_bytes(b"fake")
        mock_store.return_value = stored_path
        stored, filename, _ = await process_upload(_make_text_pdf(), "doc.pdf")
        assert "_document.pdf" in filename
        mock_md.assert_not_called()


@pytest.mark.asyncio
async def test_pipeline_fallback_on_ocr_failure(tmp_path):
    """OCR returns None → ValueError → fallback filename, no markdown."""
    from app.pipeline import process_upload

    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

    with (
        patch("app.pipeline.correct_perspective", return_value=fake_png),
        patch("app.pipeline.extract_text_from_image", return_value=None),
        patch("app.pipeline.store_file") as mock_store,
        patch("app.pipeline.store_markdown") as mock_md,
        patch("app.pipeline.insert_document", new=AsyncMock()),
    ):
        stored_path = tmp_path / "fallback.png"
        stored_path.write_bytes(b"fake")
        mock_store.return_value = stored_path
        _, filename, _ = await process_upload(fake_png, "photo.png")
        assert "_document.png" in filename
        mock_md.assert_not_called()
