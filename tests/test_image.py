"""Tests for app/image.py — correct_perspective and make_preview."""

from unittest.mock import AsyncMock, patch

import cv2
import numpy as np
import pytest

from app.image import correct_perspective, make_preview


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plain_png(width: int = 100, height: int = 120) -> bytes:
    """Small solid-grey PNG with no detectable document quad."""
    img = np.full((height, width, 3), 180, dtype=np.uint8)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return bytes(buf)


def _make_jpeg_with_rect(
    canvas_w: int = 800,
    canvas_h: int = 600,
    rect_margin: int = 60,
) -> bytes:
    """
    JPEG with a large white rectangle on a grey background.
    The rectangle covers ~67 % of the canvas area — well above the 15 % threshold.
    """
    img = np.full((canvas_h, canvas_w, 3), 80, dtype=np.uint8)
    x1, y1 = rect_margin, rect_margin
    x2, y2 = canvas_w - rect_margin, canvas_h - rect_margin
    cv2.rectangle(img, (x1, y1), (x2, y2), (255, 255, 255), -1)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])
    assert ok
    return bytes(buf)


def _make_wide_jpeg(width: int = 800, height: int = 100) -> bytes:
    img = np.full((height, width, 3), 100, dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return bytes(buf)


def _make_small_jpeg(width: int = 50, height: int = 60) -> bytes:
    img = np.full((height, width, 3), 150, dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return bytes(buf)


# ---------------------------------------------------------------------------
# correct_perspective
# ---------------------------------------------------------------------------

def test_correct_perspective_plain_png_returns_original():
    """No quad detectable → original bytes returned unchanged."""
    data = _make_plain_png()
    result = correct_perspective(data)
    assert result == data


def test_correct_perspective_detects_rect_and_warps():
    """Large white rectangle should be detected; output width == 794."""
    data = _make_jpeg_with_rect()
    result = correct_perspective(data)
    assert result != data  # transformed
    arr = np.frombuffer(result, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    assert img is not None
    assert img.shape[1] == 794  # out_w fixed to 794


def test_correct_perspective_invalid_bytes_returns_input():
    """Garbage bytes → decode fails → original returned."""
    garbage = b"\x00\x01\x02\x03garbage"
    assert correct_perspective(garbage) == garbage


def test_correct_perspective_empty_bytes_returns_input():
    assert correct_perspective(b"") == b""


# ---------------------------------------------------------------------------
# make_preview
# ---------------------------------------------------------------------------

def test_make_preview_returns_data_uri():
    data = _make_wide_jpeg()
    uri = make_preview(data)
    assert uri.startswith("data:image/jpeg;base64,")


def test_make_preview_downsamples_wide_image():
    data = _make_wide_jpeg(width=800)
    uri = make_preview(data, max_width=400)
    assert uri.startswith("data:image/jpeg;base64,")
    # Decode and check width
    import base64
    b64_part = uri.split(",", 1)[1]
    img_bytes = base64.b64decode(b64_part)
    arr = np.frombuffer(img_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    assert img is not None
    assert img.shape[1] == 400


def test_make_preview_does_not_upscale_small_image():
    data = _make_small_jpeg(width=50)
    uri = make_preview(data, max_width=400)
    import base64
    b64_part = uri.split(",", 1)[1]
    img_bytes = base64.b64decode(b64_part)
    arr = np.frombuffer(img_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    assert img is not None
    assert img.shape[1] == 50  # unchanged


def test_make_preview_invalid_bytes_returns_empty():
    assert make_preview(b"not-an-image") == ""


def test_make_preview_empty_bytes_returns_empty():
    assert make_preview(b"") == ""


# ---------------------------------------------------------------------------
# Integration: process_upload
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_upload_image_returns_preview(tmp_path):
    """Image uploads should produce a non-empty preview_b64."""
    from app.agents import DocumentMetadata
    from app.pipeline import process_upload

    jpeg_bytes = _make_wide_jpeg()
    mock_meta = DocumentMetadata(date="2024-01-01", tags=["photo"])

    with (
        patch("app.pipeline.correct_perspective", return_value=jpeg_bytes),
        patch("app.pipeline.extract_text_from_image", return_value="x" * 60),
        patch("app.pipeline.classify_text", new=AsyncMock(return_value=mock_meta)),
        patch("app.pipeline.store_file") as mock_store,
        patch("app.pipeline.store_markdown"),
        patch("app.pipeline.insert_document", new=AsyncMock()),
    ):
        stored_path = tmp_path / "2024-01-01_photo.jpg"
        stored_path.write_bytes(b"fake")
        mock_store.return_value = stored_path
        _, _, preview_b64 = await process_upload(jpeg_bytes, "photo.jpg")

    assert preview_b64.startswith("data:image/jpeg;base64,")


@pytest.mark.asyncio
async def test_process_upload_text_pdf_returns_empty_preview(tmp_path):
    """Text PDFs should return preview_b64 == ''."""
    import fitz

    from app.agents import DocumentMetadata
    from app.pipeline import process_upload

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 72), "Invoice 2024-01-01 " + "x" * 200)
    pdf_bytes = doc.tobytes()

    mock_meta = DocumentMetadata(date="2024-01-01", tags=["invoice"])

    with (
        patch("app.pipeline.classify_text", new=AsyncMock(return_value=mock_meta)),
        patch("app.pipeline.store_file") as mock_store,
        patch("app.pipeline.store_markdown"),
        patch("app.pipeline.insert_document", new=AsyncMock()),
    ):
        stored_path = tmp_path / "2024-01-01_invoice.pdf"
        stored_path.write_bytes(b"fake")
        mock_store.return_value = stored_path
        _, _, preview_b64 = await process_upload(pdf_bytes, "doc.pdf")

    assert preview_b64 == ""
