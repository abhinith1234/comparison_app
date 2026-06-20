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


def detect_form_boxes_categorized(bgr: np.ndarray) -> tuple[list[Box], list[Box]]:
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
    # A single form fills the frame: nothing useful to split, treated as full
    if len(boxes) <= 1:
        return [(0, 0, W, H)], []

    # Calculate median height of detected boxes
    median_h = float(np.median([b[3] for b in boxes]))

    full_boxes = []
    partial_boxes = []
    for box in boxes:
        x, y, w, h = box
        # If height is significantly smaller than the median height, it is partial
        if h < median_h * 0.88:
            partial_boxes.append(box)
        # If it touches the top/bottom boundary and is smaller than typical height
        elif (y <= 15 or (y + h) >= H - 15) and h < median_h * 0.96:
            partial_boxes.append(box)
        else:
            full_boxes.append(box)

    row_tol = int(median_h * 0.5)
    full_ordered = _reading_order(full_boxes, row_tol)
    partial_ordered = _reading_order(partial_boxes, row_tol)

    return full_ordered, partial_ordered


def detect_form_boxes(bgr: np.ndarray) -> list[Box]:
    full_boxes, _ = detect_form_boxes_categorized(bgr)
    return full_boxes


def crop_boxes(bgr: np.ndarray, boxes: list[Box], pad: int = 4) -> list[np.ndarray]:
    H, W = bgr.shape[:2]
    crops = []
    for x, y, w, h in boxes:
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(W, x + w + pad), min(H, y + h + pad)
        crops.append(bgr[y0:y1, x0:x1])
    return crops
