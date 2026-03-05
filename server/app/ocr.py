import logging

import cv2
import numpy as np
import pytesseract

from app.config import settings

logger = logging.getLogger(__name__)

_MIN_TEXT_CHARS = 50  # mirrors the per-page threshold in pdf.py

# Tesseract OSD "rotate" value → cv2 rotation code (CCW convention)
_CV2_ROTATE = {
    90: cv2.ROTATE_90_COUNTERCLOCKWISE,
    180: cv2.ROTATE_180,
    270: cv2.ROTATE_90_CLOCKWISE,
}


def _preprocess(image_bytes: bytes) -> np.ndarray | None:
    """Decode + grayscale. Returns numpy array or None."""
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return None
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def _auto_rotate(gray: np.ndarray) -> np.ndarray:
    """Use Tesseract OSD to detect and correct image rotation (0/90/180/270°)."""
    try:
        osd = pytesseract.image_to_osd(gray, output_type=pytesseract.Output.DICT)
        rotate = int(osd.get("rotate", 0))
    except Exception:
        return gray
    code = _CV2_ROTATE.get(rotate)
    if code is None:
        return gray
    logger.debug("[ocr] rotating image by %d°", rotate)
    return cv2.rotate(gray, code)


def extract_text_from_image(image_bytes: bytes) -> str | None:
    """
    Run Tesseract OCR. Returns extracted text, or None if:
    - bytes empty/invalid
    - result < _MIN_TEXT_CHARS chars
    - Tesseract binary unavailable or crashes
    """
    if not image_bytes:
        return None
    processed = _preprocess(image_bytes)
    if processed is None:
        logger.warning("[ocr] failed to decode image bytes")
        return None
    rotated = _auto_rotate(processed)
    try:
        text: str = pytesseract.image_to_string(rotated, lang=settings.ocr_lang)
    except pytesseract.TesseractError as exc:
        logger.warning("[ocr] Tesseract error: %s", exc)
        return None
    text = text.strip()
    if len(text) < _MIN_TEXT_CHARS:
        logger.debug("[ocr] too short (%d chars), treating as no text", len(text))
        return None
    logger.debug("[ocr] extracted %d chars (lang=%r)", len(text), settings.ocr_lang)
    return text
