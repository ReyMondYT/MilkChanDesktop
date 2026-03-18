import os
import time
from typing import Optional, Tuple

import numpy as np
from PIL import Image
from PyQt5.QtCore import QThread, pyqtSignal

from milkchan.desktop.utils.screenshot import take_screenshot


class ScreenWatcher(QThread):
    """
    Periodically takes low-res screenshots, compares to the previous frame,
    and emits a change_detected signal when the changed area exceeds a threshold.

    Signals:
      - change_detected: emits a dict with keys:
          {
            'before_path': str,
            'after_path': str,
            'diff_ratio': float,               # fraction of pixels changed (0-1)
            'bbox': [ymin, xmin, ymax, xmax],  # approximate changed region in screen coords
            'hint': str
          }
    """
    change_detected = pyqtSignal(object)

    def __init__(self, config: dict):
        super().__init__()
        self.cfg = config or {}
        proactive = (self.cfg.get('proactive') or {})
        self.enabled = bool(proactive.get('enabled', True))
        self.sample_interval = float(proactive.get('sample_interval_ms', 1000)) / 1000.0
        self.change_threshold = float(proactive.get('change_threshold', 0.12))      # fraction pixels changed
        self.pixel_delta = float(proactive.get('pixel_delta', 0.10))                # per-pixel diff threshold (0-1)
        self.min_interval_sec = float(proactive.get('min_interval_sec', 15.0))
        proc = (self.cfg.get('processing') or {})
        self.resize_factor = float(proc.get('video_resize_factor', 0.35))

        self._prev_gray: Optional[np.ndarray] = None
        self._prev_path: Optional[str] = None
        self._last_event_ts = 0.0
        self._paused = False
        self._stop = False
        # ignore_region: (x, y, w, h) in screen coords
        self._ignore_region: Optional[Tuple[int, int, int, int]] = None

    def set_paused(self, paused: bool):
        self._paused = bool(paused)

    def stop(self):
        self._stop = True

    def update_config(self, cfg: dict):
        self.cfg = cfg or self.cfg
        proactive = (self.cfg.get('proactive') or {})
        self.enabled = bool(proactive.get('enabled', True))
        self.sample_interval = float(proactive.get('sample_interval_ms', 1000)) / 1000.0
        self.change_threshold = float(proactive.get('change_threshold', 0.12))
        self.pixel_delta = float(proactive.get('pixel_delta', 0.10))
        self.min_interval_sec = float(proactive.get('min_interval_sec', 15.0))
        proc = (self.cfg.get('processing') or {})
        self.resize_factor = float(proc.get('video_resize_factor', 0.35))

    def update_ignore_region(self, x: int, y: int, w: int, h: int):
        # Region where differences will be ignored (e.g., sprite overlay)
        self._ignore_region = (int(x), int(y), int(w), int(h))

    def _load_gray(self, path: str) -> Optional[np.ndarray]:
        # Retry a few times in case the file is not fully released yet
        for _ in range(3):
            try:
                with Image.open(path) as im:
                    arr = np.asarray(im.convert('L'), dtype=np.float32) / 255.0
                    return arr
            except Exception:
                time.sleep(0.05)
        return None

    def _apply_ignore_to_mask(self, mask: np.ndarray):
        if not self._ignore_region:
            return
        x, y, w, h = self._ignore_region
        rf = max(0.1, min(1.0, float(self.resize_factor or 1.0)))
        sx = int(x * rf)
        sy = int(y * rf)
        ex = int((x + w) * rf)
        ey = int((y + h) * rf)
        H, W = mask.shape
        sx = max(0, min(W, sx))
        ex = max(0, min(W, ex))
        sy = max(0, min(H, sy))
        ey = max(0, min(H, ey))
        if sy < ey and sx < ex:
            mask[sy:ey, sx:ex] = False

    def _mask_to_screen_bbox(self, mask: np.ndarray) -> Optional[list]:
        ys, xs = np.where(mask)
        if ys.size == 0 or xs.size == 0:
            return None
        rf = max(0.1, min(1.0, float(self.resize_factor or 1.0)))
        y_min = int(ys.min() / rf)
        y_max = int(ys.max() / rf)
        x_min = int(xs.min() / rf)
        x_max = int(xs.max() / rf)
        return [y_min, x_min, y_max, x_max]

    def run(self):
        # Initial priming screenshot
        if not self.enabled:
            return
        while not self._stop:
            try:
                if self._paused or not self.enabled:
                    time.sleep(self.sample_interval)
                    continue

                ss = take_screenshot(self.resize_factor)
                if not ss:
                    time.sleep(self.sample_interval)
                    continue
                curr_path, out_w, out_h = ss
                curr_gray = self._load_gray(curr_path)
                if curr_gray is None:
                    try:
                        if os.path.exists(curr_path):
                            os.remove(curr_path)
                    except Exception:
                        pass
                    time.sleep(self.sample_interval)
                    continue

                if self._prev_gray is None:
                    self._prev_gray = curr_gray
                    self._prev_path = curr_path
                    time.sleep(self.sample_interval)
                    continue

                # Ensure same shape; if not, reset baseline
                if self._prev_gray.shape != curr_gray.shape:
                    try:
                        if os.path.exists(self._prev_path or ''):
                            os.remove(self._prev_path)
                    except Exception:
                        pass
                    self._prev_gray = curr_gray
                    self._prev_path = curr_path
                    time.sleep(self.sample_interval)
                    continue

                delta = np.abs(curr_gray - self._prev_gray)
                diff_mask = delta > self.pixel_delta

                # Ignore overlay/sprite region differences
                self._apply_ignore_to_mask(diff_mask)

                diff_ratio = float(diff_mask.mean())

                now = time.time()
                if diff_ratio >= self.change_threshold and (now - self._last_event_ts) >= self.min_interval_sec:
                    bbox = self._mask_to_screen_bbox(diff_mask) or []
                    hint = f"Screen content changed (~{int(diff_ratio * 100)}% of pixels)."
                    payload = {
                        'before_path': self._prev_path,
                        'after_path': curr_path,
                        'diff_ratio': diff_ratio,
                        'bbox': bbox,
                        'hint': hint,
                    }
                    self._last_event_ts = now
                    # Emit event with both paths; the consumer should delete both after use
                    self.change_detected.emit(payload)

                    # Prepare baseline for next cycle (do not delete files here)
                    self._prev_gray = curr_gray
                    self._prev_path = curr_path
                else:
                    # Update baseline, cleanup previous file
                    try:
                        if os.path.exists(self._prev_path or ''):
                            os.remove(self._prev_path)  # cleanup previous
                    except Exception:
                        pass
                    self._prev_gray = curr_gray
                    self._prev_path = curr_path

                time.sleep(self.sample_interval)
            except Exception:
                # Never crash this thread; just delay a bit and continue
                time.sleep(self.sample_interval)
                continue