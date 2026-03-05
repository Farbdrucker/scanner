import base64

import cv2
import numpy as np


def correct_perspective(image_bytes: bytes) -> bytes:
    """
    Detect the largest document quad in the image and apply perspective correction.
    Returns original bytes unchanged if no qualifying quad is found or decode fails.
    """
    if not image_bytes:
        return image_bytes
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return image_bytes

    h, w = img.shape[:2]
    image_area = h * w

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 75, 200)
    kernel = np.ones((3, 3), np.uint8)
    dilated = cv2.dilate(edges, kernel, iterations=1)

    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best_quad = None
    best_area = 0.0
    for cnt in contours:
        peri = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
        if len(approx) != 4:
            continue
        area = cv2.contourArea(approx)
        if area < 0.15 * image_area:
            continue
        if area > best_area:
            best_area = area
            best_quad = approx

    if best_quad is None:
        return image_bytes

    src_pts = _order_points(best_quad.reshape(4, 2).astype(np.float32))

    # Compute output dimensions from quad geometry
    tl, tr, br, bl = src_pts
    w_top = float(np.linalg.norm(tr - tl))
    w_bot = float(np.linalg.norm(br - bl))
    h_left = float(np.linalg.norm(bl - tl))
    h_right = float(np.linalg.norm(br - tr))
    out_w_f = max(w_top, w_bot)
    out_h_f = max(h_left, h_right)

    aspect = out_h_f / out_w_f if out_w_f > 0 else 1.0
    aspect = max(0.8, min(2.0, aspect))

    out_w = 794
    out_h = int(out_w * aspect)

    dst_pts = np.array(
        [[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]],
        dtype=np.float32,
    )

    M = cv2.getPerspectiveTransform(src_pts, dst_pts)
    warped = cv2.warpPerspective(img, M, (out_w, out_h))

    ok, buf = cv2.imencode(".jpg", warped, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        return image_bytes
    return bytes(buf)


def make_preview(image_bytes: bytes, max_width: int = 400) -> str:
    """
    Resize image to at most max_width and return a data URI (JPEG, base64).
    Returns "" if decode fails.
    """
    if not image_bytes:
        return ""
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return ""

    h, w = img.shape[:2]
    if w > max_width:
        scale = max_width / w
        img = cv2.resize(img, (max_width, int(h * scale)), interpolation=cv2.INTER_AREA)

    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        return ""
    b64 = base64.b64encode(bytes(buf)).decode()
    return f"data:image/jpeg;base64,{b64}"


def _order_points(pts: np.ndarray) -> np.ndarray:
    """Return [TL, TR, BR, BL] ordering."""
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    tl = pts[np.argmin(s)]
    br = pts[np.argmax(s)]
    tr = pts[np.argmin(d)]
    bl = pts[np.argmax(d)]
    return np.array([tl, tr, br, bl], dtype=np.float32)
