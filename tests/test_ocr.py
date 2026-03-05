"""Unit tests for app/ocr.py — extract_text_from_image."""

from unittest.mock import patch

import cv2
import numpy as np
import pytesseract
from app.ocr import _MIN_TEXT_CHARS, _auto_rotate, extract_text_from_image


def _make_plain_png(width: int = 100, height: int = 120) -> bytes:
    """Small solid-grey PNG."""
    img = np.full((height, width, 3), 180, dtype=np.uint8)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return bytes(buf)


def test_returns_none_for_empty_bytes():
    assert extract_text_from_image(b"") is None


def test_returns_none_for_invalid_bytes():
    assert extract_text_from_image(b"\x00garbage") is None


def test_returns_none_when_ocr_result_too_short():
    png = _make_plain_png()
    with patch("pytesseract.image_to_string", return_value="ab"):
        assert extract_text_from_image(png) is None


def test_returns_text_when_ocr_succeeds():
    png = _make_plain_png()
    long_text = "a" * _MIN_TEXT_CHARS
    with patch("pytesseract.image_to_string", return_value=long_text):
        result = extract_text_from_image(png)
    assert result == long_text


def test_strips_whitespace():
    png = _make_plain_png()
    padded = "  " + "a" * _MIN_TEXT_CHARS + "\n\n"
    with patch("pytesseract.image_to_string", return_value=padded):
        result = extract_text_from_image(png)
    assert result == padded.strip()


def test_returns_none_on_tesseract_error():
    png = _make_plain_png()
    with patch(
        "pytesseract.image_to_string",
        side_effect=pytesseract.TesseractError(1, "crash"),
    ):
        assert extract_text_from_image(png) is None


def test_passes_lang_setting():
    png = _make_plain_png()
    long_text = "b" * _MIN_TEXT_CHARS
    with patch("pytesseract.image_to_string", return_value=long_text) as mock_ocr:
        extract_text_from_image(png)
    _, kwargs = mock_ocr.call_args
    from app.config import settings

    assert kwargs.get("lang") == settings.ocr_lang


def test_min_chars_boundary():
    png = _make_plain_png()
    # Exactly _MIN_TEXT_CHARS → succeeds
    exact = "x" * _MIN_TEXT_CHARS
    with patch("pytesseract.image_to_string", return_value=exact):
        assert extract_text_from_image(png) == exact

    # One fewer → None
    one_less = "x" * (_MIN_TEXT_CHARS - 1)
    with patch("pytesseract.image_to_string", return_value=one_less):
        assert extract_text_from_image(png) is None


# ---------------------------------------------------------------------------
# _auto_rotate
# ---------------------------------------------------------------------------


def _make_gray(width: int = 100, height: int = 120) -> np.ndarray:
    return np.full((height, width), 180, dtype=np.uint8)


def test_auto_rotate_no_rotation():
    gray = _make_gray()
    with patch("pytesseract.image_to_osd", return_value={"rotate": 0}):
        result = _auto_rotate(gray)
    assert result.shape == gray.shape
    np.testing.assert_array_equal(result, gray)


def test_auto_rotate_90():
    gray = _make_gray(width=100, height=120)
    with patch("pytesseract.image_to_osd", return_value={"rotate": 90}):
        result = _auto_rotate(gray)
    # 90° CCW: height and width swap
    assert result.shape == (100, 120)


def test_auto_rotate_180():
    gray = _make_gray(width=100, height=120)
    with patch("pytesseract.image_to_osd", return_value={"rotate": 180}):
        result = _auto_rotate(gray)
    assert result.shape == (120, 100)


def test_auto_rotate_270():
    gray = _make_gray(width=100, height=120)
    with patch("pytesseract.image_to_osd", return_value={"rotate": 270}):
        result = _auto_rotate(gray)
    # 90° CW: height and width swap
    assert result.shape == (100, 120)


def test_auto_rotate_osd_error_returns_original():
    """OSD failure (e.g. too few chars) → original image returned unchanged."""
    gray = _make_gray()
    with patch(
        "pytesseract.image_to_osd", side_effect=pytesseract.TesseractError(1, "too few")
    ):
        result = _auto_rotate(gray)
    np.testing.assert_array_equal(result, gray)
