"""Split a sheet containing many bordered form boxes into individual crops.

A sheet like the provided scans is a regular grid of rectangular form boxes.
We isolate the long horizontal/vertical border lines, find the rectangular cells
they form, de-duplicate overlapping detections (NMS), and return one crop per
form in reading order. If the image is a single form (no inner grid), we return
the whole image as one box.
"""
from __future__ import annotations

import cv2
import numpy as np

Box = tuple[int, int, int, int]  # x, y, w, h


def _iou(a: Box, b: Box) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    if inter == 0:
        return 0.0
    return inter / float(aw * ah + bw * bh - inter)


def _nms(boxes: list[Box], thr: float = 0.3) -> list[Box]:
    # Keep larger boxes first; drop later ones that overlap a kept box.
    boxes = sorted(boxes, key=lambda b: b[2] * b[3], reverse=True)
    kept: list[Box] = []
    for b in boxes:
        if all(_iou(b, k) < thr for k in kept):
            kept.append(b)
    return kept


def _reading_order(boxes: list[Box], row_tol: int) -> list[Box]:
    boxes = sorted(boxes, key=lambda b: b[1])
    rows: list[list[Box]] = []
    for b in boxes:
        if rows and abs(b[1] - rows[-1][0][1]) <= row_tol:
            rows[-1].append(b)
        else:
            rows.append([b])
    ordered: list[Box] = []
    for row in rows:
        ordered.extend(sorted(row, key=lambda b: b[0]))
    return ordered


def _cluster(vals: list[int], gap: float) -> list[int]:
    vals = sorted(vals)
    groups = [[vals[0]]]
    for v in vals[1:]:
        if v - groups[-1][-1] < gap:
            groups[-1].append(v)
        else:
            groups.append([v])
    return [int(np.median(g)) for g in groups]


def _fill_grid(boxes: list[Box], bgr: np.ndarray, th: np.ndarray) -> list[Box]:
    """The sheets are a regular 2-column grid. From the detected full cells infer
    the column x-positions and the row pitch, then extrapolate rows above the
    first / below the last so the partial form rows that get clipped at the very
    top or bottom of a scanned page are still cropped (they hold the other half
    of a form split across two pages). Synthesised cells are kept only if they
    actually contain ink, so empty page margins are not turned into boxes."""
    H, W = bgr.shape[:2]
    mw = int(np.median([b[2] for b in boxes]))
    mh = int(np.median([b[3] for b in boxes]))
    col_x = _cluster([b[0] for b in boxes], mw * 0.5)
    row_y = _cluster([b[1] for b in boxes], mh * 0.5)
    pitch = int(np.median(np.diff(sorted(row_y)))) if len(row_y) >= 2 else mh
    if pitch < mh * 0.5:
        pitch = mh

    min_vis = max(40, int(mh * 0.3))
    rows = set(row_y)
    y = min(row_y) - pitch
    while min(H, y + mh) - max(0, y) >= min_vis:
        rows.add(y)
        y -= pitch
    y = max(row_y) + pitch
    while min(H, y + mh) - max(0, y) >= min_vis:
        rows.add(y)
        y += pitch

    result = list(boxes)
    for ry in sorted(rows):
        for cx in col_x:
            y0, y1 = max(0, ry), min(H, ry + mh)
            cell = (cx, y0, mw, y1 - y0)
            if any(_iou(cell, b) > 0.2 for b in result):
                continue
            roi = th[y0:y1, cx:min(W, cx + mw)]
            if roi.size and float((roi > 0).mean()) > 0.02:  # has ink, not a margin
                result.append(cell)
    return result


def detect_form_boxes(bgr: np.ndarray) -> list[Box]:
    H, W = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]

    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(10, W // 12), 1))
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(10, H // 12)))
    hor = cv2.morphologyEx(th, cv2.MORPH_OPEN, hk)
    ver = cv2.morphologyEx(th, cv2.MORPH_OPEN, vk)
    grid = cv2.dilate(cv2.add(hor, ver), np.ones((3, 3), np.uint8))

    cnts, _ = cv2.findContours(grid, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    cands: list[Box] = []
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        if w > W * 0.25 and W * 0.7 > w and H * 0.05 < h < H * 0.45:
            cands.append((x, y, w, h))

    boxes = _nms(cands)
    # A single form fills the frame: nothing useful to split.
    if len(boxes) <= 1:
        return [(0, 0, W, H)]

    boxes = _fill_grid(boxes, bgr, th)
    row_tol = int(np.median([b[3] for b in boxes]) * 0.35)
    return _reading_order(boxes, row_tol)


def crop_boxes(bgr: np.ndarray, boxes: list[Box], pad: int = 4) -> list[np.ndarray]:
    H, W = bgr.shape[:2]
    crops = []
    for x, y, w, h in boxes:
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(W, x + w + pad), min(H, y + h + pad)
        crops.append(bgr[y0:y1, x0:x1])
    return crops
