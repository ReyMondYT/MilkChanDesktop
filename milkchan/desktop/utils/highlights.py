import os
from typing import Dict, Optional, Tuple

import cv2
import numpy as np


def _read_bgr(path: str, max_width: int = 960) -> Optional[np.ndarray]:
    if not path or not os.path.exists(path):
        return None
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        return None
    h, w = img.shape[:2]
    if w > max_width:
        scale = max_width / float(w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return img


def _rectangularity(contour: np.ndarray) -> float:
    if contour is None or len(contour) < 3:
        return 0.0
    area = cv2.contourArea(contour)
    x, y, w, h = cv2.boundingRect(contour)
    rect_area = float(w * h) if w > 0 and h > 0 else 1.0
    return float(area) / rect_area if rect_area > 0 else 0.0


def _edge_density(mask: np.ndarray, roi: Tuple[int, int, int, int]) -> float:
    x, y, w, h = roi
    if w <= 0 or h <= 0:
        return 0.0
    sub = mask[y : y + h, x : x + w]
    return float(cv2.countNonZero(sub)) / float(w * h)


def _hsv_hist_diff(a_bgr: np.ndarray, b_bgr: np.ndarray) -> float:
    ah = cv2.cvtColor(a_bgr, cv2.COLOR_BGR2HSV)
    bh = cv2.cvtColor(b_bgr, cv2.COLOR_BGR2HSV)
    # 2D histogram on H and S for robustness
    histSize = [32, 32]
    ranges = [0, 180, 0, 256]
    a_hist = cv2.calcHist([ah], [0, 1], None, histSize, ranges)
    b_hist = cv2.calcHist([bh], [0, 1], None, histSize, ranges)
    cv2.normalize(a_hist, a_hist, 0, 1, cv2.NORM_MINMAX)
    cv2.normalize(b_hist, b_hist, 0, 1, cv2.NORM_MINMAX)
    # Use Bhattacharyya distance (0 identical, 1 very different)
    d = cv2.compareHist(a_hist, b_hist, cv2.HISTCMP_BHATTACHARYYA)
    return float(d)


def _orb_keypoint_delta(a_bgr: np.ndarray, b_bgr: np.ndarray) -> Tuple[int, int, int]:
    orb = cv2.ORB_create(nfeatures=800)
    kp1, des1 = orb.detectAndCompute(a_bgr, None)
    kp2, des2 = orb.detectAndCompute(b_bgr, None)
    n1 = len(kp1 or [])
    n2 = len(kp2 or [])
    matches = 0
    if des1 is not None and des2 is not None and len(des1) > 0 and len(des2) > 0:
        bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        m = bf.match(des1, des2)
        matches = len(m)
    return n1, n2, matches


def _largest_changed_region(a_gray: np.ndarray, b_gray: np.ndarray) -> Tuple[Optional[Tuple[int, int, int, int]], float, float]:
    # Difference mask
    delta = cv2.absdiff(a_gray, b_gray)
    # Normalize to 0..255
    if delta.dtype != np.uint8:
        delta = np.clip(delta, 0, 255).astype(np.uint8)
    # Suppress tiny noise
    blur = cv2.GaussianBlur(delta, (5, 5), 0)
    _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # Morph to merge glyphs
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3))
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, k, iterations=2)
    contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None, 0.0, 0.0
    h, w = a_gray.shape[:2]
    total = float(w * h)
    best = max(contours, key=cv2.contourArea)
    x, y, bw, bh = cv2.boundingRect(best)
    area = float(bw * bh)
    frac = area / total if total > 0 else 0.0
    rectness = _rectangularity(best)
    return (x, y, bw, bh), float(frac), float(rectness)


def _region_location_hint(x: int, y: int, w: int, h: int, W: int, H: int) -> str:
    cx, cy = x + w // 2, y + h // 2
    horiz = 'left' if cx < W * 0.33 else ('right' if cx > W * 0.66 else 'center')
    vert = 'top' if cy < H * 0.33 else ('bottom' if cy > H * 0.66 else 'middle')
    return f"{vert}-{horiz}"


def detect_highlight(before_path: str, after_path: str) -> Dict:
    """
    Lightweight, non-LLM highlight detector.
    Returns a dict with keys:
      - type: str (one of: scene_change, dialog, notification, scroll, minor, success, error, unknown)
      - summary: short natural text
      - bbox: [ymin, xmin, ymax, xmax] or [] if N/A
      - score: float 0..1 importance
    """
    a = _read_bgr(before_path)
    b = _read_bgr(after_path)
    if a is None or b is None:
        return {"type": "unknown", "summary": "Something changed on screen.", "bbox": [], "score": 0.3}

    Ha, Wa = a.shape[:2]
    Hb, Wb = b.shape[:2]
    if (Ha, Wa) != (Hb, Wb):
        # Size changed → likely app switch or resolution change
        t = "scene_change"
        return {"type": t, "summary": "You switched screens or windows.", "bbox": [], "score": 0.85}

    gray_a = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)

    # Core signals
    hist_diff = _hsv_hist_diff(a, b)  # 0 identical .. 1 very different
    n1, n2, matches = _orb_keypoint_delta(a, b)
    kp_delta = max(0, n2 - matches)
    bbox, frac, rectness = _largest_changed_region(gray_a, gray_b)

    # Edge density in region
    edges = cv2.Canny(gray_b, 100, 200)
    edge_density = 0.0
    if bbox is not None:
        x, y, w, h = bbox
        edge_density = _edge_density(edges, (x, y, w, h))

    # Heuristics
    H, W = gray_b.shape[:2]
    t: str
    msg: str
    score: float
    out_bbox = []

    if hist_diff > 0.45 and matches < 80:
        t, msg, score = "scene_change", "Looks like you switched apps or views.", 0.9
    elif bbox is not None and 0.04 <= frac <= 0.55 and rectness >= 0.70:
        loc = _region_location_hint(*bbox, W, H)
        # Success/error color hint from mean HSV in bbox
        x, y, w, h = bbox
        roi = cv2.cvtColor(b[y : y + h, x : x + w], cv2.COLOR_BGR2HSV)
        mean_hsv = cv2.mean(roi)[:3]
        hue = mean_hsv[0]
        sat = mean_hsv[1]
        if sat > 60 and (hue < 10 or hue > 170):
            t, msg, score = "error", "A warning or error dialog appeared.", 0.85
        elif sat > 60 and 35 < hue < 85:
            t, msg, score = "success", "A confirmation or success message popped up.", 0.8
        else:
            if edge_density > 0.08 and (y < H * 0.25 or y + h > H * 0.75 or x < W * 0.25 or x + w > W * 0.75):
                t, msg, score = "notification", f"A notification showed up ({loc}).", 0.75
            else:
                t, msg, score = "dialog", "A dialog window opened.", 0.78
        out_bbox = [y, x, y + h, x + w]
    elif bbox is not None and frac < 0.035:
        # Small area changes – consider minor unless very text-like (high edges)
        if edge_density > 0.12 and (y < H * 0.2 or y + h > H * 0.8):
            t, msg, score = "notification", "A small notification appeared.", 0.6
            x, y, w, h = bbox
            out_bbox = [y, x, y + h, x + w]
        else:
            t, msg, score = "minor", "Small screen changes detected.", 0.25
    else:
        # Consider scroll if the change is band-like
        if bbox is not None:
            x, y, w, h = bbox
            aspect = float(w) / float(h + 1e-6)
            if aspect > 3.5 and 0.05 < (h / float(H)) < 0.45:
                t, msg, score = "scroll", "You scrolled or a list updated.", 0.55
                out_bbox = [y, x, y + h, x + w]
            else:
                t, msg, score = "unknown", "The screen updated.", 0.4
        else:
            t, msg, score = "unknown", "The screen updated.", 0.4

    # Boost with ORB novelty
    novelty = np.tanh(max(0, kp_delta - 60) / 120.0)  # 0..1
    score = float(np.clip(score + 0.2 * novelty + 0.4 * np.clip(hist_diff - 0.25, 0, 1), 0, 1))

    return {"type": t, "summary": msg, "bbox": out_bbox, "score": score}


def compose_message(event: Dict) -> Tuple[str, Dict]:
    """
    Compose a short in-character message and a simple emotion from the highlight event.
    Returns: (text, emotion_dict)
    """
    etype = (event.get("type") or "unknown").lower()
    score = float(event.get("score") or 0.0)
    base = {
        "scene_change": [
            "Oh! Looks like you swapped to a different screen.",
            "New view detected—did you just switch apps?",
        ],
        "dialog": [
            "A dialog just popped up.",
            "I see a window opened on top.",
        ],
        "notification": [
            "You got a little notification.",
            "A toast showed up for a moment.",
        ],
        "success": [
            "Nice—looks like a success message!",
            "That looks like a confirmation banner.",
        ],
        "error": [
            "Heads up—this looks like an error or warning.",
            "I’m seeing a red warning on screen.",
        ],
        "scroll": [
            "I noticed some scrolling.",
            "Content moved—looks like you scrolled.",
        ],
        "minor": [
            "Small change detected.",
            "A tiny update on the screen.",
        ],
        "unknown": [
            "Something changed on screen.",
            "The view updated a bit.",
        ],
    }
    options = base.get(etype, base["unknown"])
    # Deterministic pick based on score bucket
    idx = 0 if score < 0.7 else 1 if len(options) > 1 else 0
    text = options[idx]

    # Emotion mapping
    emo_map = {
        "scene_change": ["arms_down", "neutral", 1],
        "dialog": ["arms_down", "neutral", 2],
        "notification": ["one_arm", "smile", 1],
        "success": ["arms_down", "smile", 2],
        "error": ["arms_down", "sad", 2],
        "scroll": ["one_arm", "neutral", 1],
        "minor": ["one_arm", "neutral", 1],
        "unknown": ["arms_down", "neutral", 1],
    }
    emotion = {"emotion": emo_map.get(etype, emo_map["unknown"])}
    return text, emotion


