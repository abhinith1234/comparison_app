"""OCR engine: strong image preprocessing + PaddleOCR (PP-OCR), local/offline.

Preprocessing (grayscale -> upscale -> CLAHE contrast -> denoise -> unsharp) is
the single biggest accuracy lever for scanned forms, followed by PaddleOCR which
is more accurate than EasyOCR on dense printed text. Recognised boxes are
reassembled into human reading order (top-to-bottom, left-to-right) so the
positional comparator sees values in the same sequence as the form.
"""

import io
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
from PIL import Image, ImageOps

# These flags are set before importing Paddle to avoid known CPU runtime issues
# on some environments.
os.environ.setdefault("FLAGS_use_mkldnn", "0")
os.environ.setdefault("FLAGS_enable_pir_api", "0")
os.environ.setdefault("FLAGS_allocator_strategy", "auto_growth")

try:
    import paddle
except ImportError:
    paddle = None

try:
    from paddleocr import PaddleOCR
except ImportError:
    PaddleOCR = None

# OCR works on images whose width sits in [TARGET_WIDTH, MAX_WIDTH]: small crops
# are upscaled; very large images are downscaled so OCR stays bounded.
# 1600px gives significantly more character detail than 1100px for scanned forms
# (equivalent to ~150-200 DPI), which is the single biggest accuracy lever.
TARGET_WIDTH = int(os.environ.get("OCR_WIDTH", 1600))
MAX_WIDTH = int(os.environ.get("OCR_MAX_WIDTH", 2400))

# Recognition model: "default" (more accurate) or "mobile" (faster, slightly
# less accurate). We keep the default as "default" here so OCR quality is not
# reduced unless the user explicitly opts into a lighter model.
OCR_MODEL = os.environ.get("OCR_MODEL", "default").lower()
OCR_DEVICE = os.environ.get("OCR_DEVICE", "auto").lower()
OCR_SERIAL = os.environ.get("OCR_SERIAL", "0").lower() in {"1", "true", "yes", "on"}

# How many OCR worker threads to run in parallel. For CPU workloads we cap the
# default to 2 to avoid oversubscription on large images; override with
# OCR_WORKERS if you want more parallelism.
MAX_WORKERS = int(os.environ.get("OCR_WORKERS", min(2, os.cpu_count() or 2)))


def _is_gpu_available() -> bool:
    if paddle is None:
        return False
    try:
        return bool(
            paddle.device.is_compiled_with_cuda()
            and paddle.device.cuda.device_count() > 0
        )
    except Exception:  # noqa: BLE001
        return False


USE_GPU = OCR_DEVICE == "gpu" or (OCR_DEVICE == "auto" and _is_gpu_available())

_local = threading.local()
_executor = None
_exec_lock = threading.Lock()


def _get_ocr():
    ocr = getattr(_local, "ocr", None)
    if ocr is None:
        if PaddleOCR is None:
            raise RuntimeError(
                "PaddleOCR is not installed. Install backend requirements first."
            )

        common = dict(
            lang="en",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )

        # Use the PaddleOCR-supported runtime config instead of the older
        # `use_gpu` argument that this installed version rejects.
        if USE_GPU:
            common.update(
                {
                    "device": "gpu",
                    "enable_mkldnn": False,
                }
            )
        else:
            common.update(
                {
                    "device": "cpu",
                    "enable_mkldnn": False,
                }
            )
        if OCR_MODEL == "mobile":
            try:
                ocr = PaddleOCR(
                    text_detection_model_name="PP-OCRv5_mobile_det",
                    text_recognition_model_name="PP-OCRv5_mobile_rec",
                    **common,
                )
            except Exception:  # noqa: BLE001  fall back if models aren't available
                ocr = PaddleOCR(**common)
        else:
            ocr = PaddleOCR(**common)
        _local.ocr = ocr
    return ocr


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        with _exec_lock:
            if _executor is None:
                _executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
    return _executor


def extract_text_batch(images: list[bytes]) -> list[str]:
    """OCR many images, preserving input order.

    For small batches (and on Windows) the serial path is often faster because it
    avoids repeated thread startup and model contention. GPU mode is always serial.
    """
    if not images:
        return []
    if USE_GPU or OCR_SERIAL or len(images) <= 1:
        return [extract_text(image) for image in images]
    return list(_get_executor().map(extract_text, images))


def _remove_underlines(gray: np.ndarray) -> np.ndarray:
    """Erase the long horizontal field underlines.

    The underline merges with letter descenders (q, g, p, y, j) and makes the
    OCR confuse them (e.g. q -> g). We detect long horizontal runs and paint
    them back to the page background so only the glyphs remain.
    """
    binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    # Use width/20 (not /30) to also catch shorter underline segments that sit
    # directly under a single descender character (q, p, y, j).
    line_len = max(20, gray.shape[1] // 20)
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (line_len, 1))
    lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, h_kernel, iterations=1)
    # Inpaint radius 5 (was 3) so the descender strokes that cross the line are
    # reconstructed more completely, preventing q->g OCR errors.
    return cv2.inpaint(gray, lines, 5, cv2.INPAINT_TELEA)


def _deskew(gray: np.ndarray) -> np.ndarray:
    """Detect and correct small rotations (≤ 5°) caused by scanner placement.

    Even a 1–2° tilt noticeably degrades PaddleOCR accuracy on dense printed
    forms because the text-line grouping relies on horizontal alignment.
    We use Hough lines on the edge image to find the dominant near-horizontal
    angle and rotate the image to compensate.
    """
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180, threshold=80,
        minLineLength=gray.shape[1] // 5, maxLineGap=10,
    )
    if lines is None:
        return gray
    angles = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        if x2 != x1:
            angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
            if abs(angle) < 5.0:   # only correct genuine small skew
                angles.append(angle)
    if not angles:
        return gray
    skew = float(np.median(angles))
    if abs(skew) < 0.2:            # < 0.2° is noise, not a real tilt
        return gray
    h, w = gray.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), skew, 1.0)
    return cv2.warpAffine(
        gray, M, (w, h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )


def _preprocess(image_bytes: bytes) -> tuple[np.ndarray, float]:
    """Return (preprocessed BGR, scale) where scale is preprocessed/original size
    so OCR pixel coordinates can be mapped back onto the original image.

    Pipeline (each step builds on the previous):
      1. Lanczos upscale to TARGET_WIDTH for maximum character detail
      2. Deskew  – correct scanner tilt before underline removal
      3. Remove underlines – inpaint horizontal rules so descenders survive intact
      4. CLAHE   – local contrast boost (clipLimit 3, 4×4 tiles for dense forms)
      5. Bilateral filter – edge-preserving denoise (keeps character edges sharp;
         replaces fastNlMeansDenoising which blurs fine strokes)
      6. Unsharp mask (σ=1.5, 1.4/−0.4) – crisp edges without ringing
      7. Morph close (2×1 kernel) – reconnect broken horizontal strokes in
         thin fonts without merging adjacent characters
    """
    image = Image.open(io.BytesIO(image_bytes))
    image = ImageOps.exif_transpose(image).convert("L")
    arr = np.array(image)

    # 1. Scale to target width
    scale = 1.0
    h, w = arr.shape[:2]
    target = TARGET_WIDTH if w < TARGET_WIDTH else (MAX_WIDTH if w > MAX_WIDTH else 0)
    if target:
        scale = target / float(w)
        interp = cv2.INTER_LANCZOS4 if scale > 1 else cv2.INTER_AREA
        arr = cv2.resize(arr, (int(w * scale), int(h * scale)), interpolation=interp)

    # 2. Deskew (must come before underline removal – underlines are horizontal)
    arr = _deskew(arr)

    # 3. Remove horizontal underlines / field rules
    arr = _remove_underlines(arr)

    # 4. CLAHE: smaller tiles (4×4 vs 8×8) give finer local adaptation on
    #    the dense, variably-lit fields of a scanned insurance form.
    #    Higher clipLimit (3.0 vs 2.0) pulls out faint lightly-printed text.
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
    arr = clahe.apply(arr)

    # 5. Bilateral filter: unlike fastNlMeansDenoising, it preserves the
    #    sharp step-edges at character boundaries while still smoothing
    #    scanner noise in uniform background regions.
    arr = cv2.bilateralFilter(arr, d=5, sigmaColor=30, sigmaSpace=30)

    # 6. Conservative unsharp mask: σ=1.5 targets the character-stroke
    #    frequency band; weight 1.4/−0.4 sharpens without the ringing
    #    artefacts that 1.6/−0.6 at σ=3 can introduce on thin strokes.
    blur = cv2.GaussianBlur(arr, (0, 0), 1.5)
    arr = cv2.addWeighted(arr, 1.4, blur, -0.4, 0)

    # 7. Morphological closing (2 px wide, 1 px tall): closes tiny horizontal
    #    gaps in thin-font characters (e.g. broken crossbars of 'e', 'f') so
    #    the OCR model sees complete glyphs. The 1-pixel height means we
    #    never merge two vertically stacked characters.
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 1))
    arr = cv2.morphologyEx(arr, cv2.MORPH_CLOSE, kernel)

    return cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR), scale


def _reading_order(texts, polys) -> str:
    items = []
    heights = []
    for text, poly in zip(texts, polys):
        pts = np.asarray(poly, dtype=float).reshape(-1, 2)
        cy = float(pts[:, 1].mean())
        cx = float(pts[:, 0].mean())
        items.append([cy, cx, text])
        heights.append(float(pts[:, 1].max() - pts[:, 1].min()))

    if not items:
        return ""

    row_gap = (np.median(heights) if heights else 20.0) * 0.6
    items.sort(key=lambda it: (it[0], it[1]))

    lines = []
    current = [items[0]]
    line_cy = items[0][0]
    for cy, cx, text in items[1:]:
        if abs(cy - line_cy) <= row_gap:
            current.append([cy, cx, text])
            line_cy = sum(it[0] for it in current) / len(current)
        else:
            lines.append(current)
            current = [[cy, cx, text]]
            line_cy = cy
    lines.append(current)

    out = []
    for line in lines:
        line.sort(key=lambda it: it[1])
        out.append(" ".join(it[2] for it in line))
    return "\n".join(out)


def _reading_order_with_boxes(texts, polys):
    """Like _reading_order, but also return a per-word bounding box (x0,y0,x1,y1)
    aligned 1:1 with the whitespace-separated words of the returned text. Words
    coming from the same detection share that detection's box."""
    items = []
    heights = []
    for text, poly in zip(texts, polys):
        pts = np.asarray(poly, dtype=float).reshape(-1, 2)
        cy = float(pts[:, 1].mean())
        cx = float(pts[:, 0].mean())
        bbox = (
            float(pts[:, 0].min()),
            float(pts[:, 1].min()),
            float(pts[:, 0].max()),
            float(pts[:, 1].max()),
        )
        items.append([cy, cx, text, bbox])
        heights.append(bbox[3] - bbox[1])

    if not items:
        return "", []

    row_gap = (np.median(heights) if heights else 20.0) * 0.6
    items.sort(key=lambda it: (it[0], it[1]))

    lines = []
    current = [items[0]]
    line_cy = items[0][0]
    for it in items[1:]:
        if abs(it[0] - line_cy) <= row_gap:
            current.append(it)
            line_cy = sum(x[0] for x in current) / len(current)
        else:
            lines.append(current)
            current = [it]
            line_cy = it[0]
    lines.append(current)

    out_lines = []
    word_boxes = []
    for line in lines:
        line.sort(key=lambda it: it[1])
        words = []
        for _, _, text, bbox in line:
            for word in text.split():
                words.append(word)
                word_boxes.append(bbox)
        out_lines.append(" ".join(words))
    return "\n".join(out_lines), word_boxes


def _run_paddle_detail(bgr: np.ndarray):
    ocr = _get_ocr()
    result = ocr.predict(bgr)
    if not result:
        return "", []
    res = result[0]
    texts = res.get("rec_texts") or []
    polys = res.get("rec_polys")
    if polys is None:
        polys = res.get("dt_polys") or res.get("rec_boxes") or []
    return _reading_order_with_boxes(texts, polys)


def extract_text(image_bytes: bytes) -> str:
    """Run OCR on raw image bytes and return recognised text in reading order."""
    bgr, _ = _preprocess(image_bytes)
    text, _ = _run_paddle_detail(bgr)
    return text


def extract_text_detail(image_bytes: bytes) -> dict:
    """OCR plus per-word boxes. `token_boxes[i]` is (x0,y0,x1,y1) in the ORIGINAL
    image's pixel coordinates for the i-th whitespace-separated word of `text`."""
    bgr, scale = _preprocess(image_bytes)
    text, boxes = _run_paddle_detail(bgr)
    inv = 1.0 / scale if scale else 1.0
    token_boxes = [
        [x0 * inv, y0 * inv, x1 * inv, y1 * inv] for (x0, y0, x1, y1) in boxes
    ]
    return {"text": text, "token_boxes": token_boxes}


def extract_text_detail_batch(images: list[bytes]) -> list[dict]:
    """Run OCR detail extraction, preserving input order.

    Exact one-image or small batches are usually faster when serialized, so we
    avoid the thread pool unless the batch is large enough to justify it.
    """
    if not images:
        return []
    if USE_GPU or OCR_SERIAL or len(images) <= 1:
        return [extract_text_detail(image) for image in images]
    return list(_get_executor().map(extract_text_detail, images))


def _classify_sign_shape(roi: np.ndarray):
    """Decide '+' vs '-' from a tiny sign crop by stroke geometry: a '+' has a
    tall vertical stroke, a '-' is only a short horizontal bar. Returns '+'/'-'
    or None when the region is effectively blank (no sign present)."""
    if roi is None or roi.size == 0:
        return None
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi
    th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    ink = th > 0
    if float(ink.mean()) < 0.03:  # essentially blank -> no sign there
        return None
    h = th.shape[0]
    tallest = int(ink.sum(axis=0).max())  # max ink height of any single column
    return "+" if tallest >= 0.5 * h else "-"


def recover_blood_sign(crop: np.ndarray, letter_box, limit_x=None):
    """Try to recover a dropped blood-group +/- sign from the form crop.

    1) Re-OCR a zoomed-in patch covering the letter + the space where the sign
       sits; if OCR now reads a +/- (or a look-alike), use it.
    2) Otherwise classify the stroke shape just right of the letter (+ vs -).
    Returns '+'/'-' or None if the sign genuinely isn't there.
    """
    if crop is None or getattr(crop, "size", 0) == 0 or not letter_box:
        return None
    h, w = crop.shape[:2]
    x0, y0, x1, y1 = (int(round(v)) for v in letter_box)
    lw = max(1, x1 - x0)
    lh = max(1, y1 - y0)
    right = int(limit_x) if limit_x else x1 + int(lw * 2.2)
    right = max(x1 + 2, min(w, right))

    # 1) zoomed re-OCR of the letter + sign region
    rx0 = max(0, x0 - lw // 4)
    ry0 = max(0, y0 - lh // 4)
    ry1 = min(h, y1 + lh // 4)
    if right - rx0 >= 4 and ry1 - ry0 >= 4:
        patch = crop[ry0:ry1, rx0:right]
        big = cv2.resize(patch, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        try:
            txt = extract_text(cv2.imencode(".png", big)[1].tobytes())
        except Exception:  # noqa: BLE001
            txt = ""
        comp = txt.upper().replace(" ", "")
        if "+" in comp:
            return "+"
        if any(c in comp for c in "-—–~_"):
            return "-"

    # 2) geometric fallback: examine just the strip to the right of the letter
    sx0 = min(w - 1, x1)
    sy0 = max(0, y0 - lh // 6)
    sy1 = min(h, y1 + lh // 6)
    if right - sx0 >= 2 and sy1 - sy0 >= 2:
        return _classify_sign_shape(crop[sy0:sy1, sx0:right])
    return None
