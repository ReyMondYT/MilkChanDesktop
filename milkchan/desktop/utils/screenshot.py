"""Capture the primary monitor as one compact JPEG for the chat request."""

import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

from PIL import Image

from milkchan.paths import get_user_data_dir

logger = logging.getLogger(__name__)

SCREENSHOT_DIR = get_user_data_dir() / 'screenshots'


def take_screenshot(resize_factor: float = 1.0) -> Optional[Path]:
    """Return the path of a new JPEG (the caller deletes it), or None on failure."""
    try:
        import mss

        with mss.mss() as capture:
            shot = capture.grab(capture.monitors[1])
        image = Image.frombytes('RGB', shot.size, shot.bgra, 'raw', 'BGRX')
        factor = max(0.1, min(1.0, float(resize_factor)))
        if factor < 1.0:
            image = image.resize(
                (max(2, round(image.width * factor)), max(2, round(image.height * factor))),
                Image.Resampling.LANCZOS,
            )
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(suffix='.jpg', prefix='screenshot_', dir=SCREENSHOT_DIR)
        try:
            with os.fdopen(fd, 'wb') as output:
                image.save(output, format='JPEG', quality=80, optimize=True)
        except Exception:
            os.unlink(name)
            raise
        return Path(name)
    except Exception as exc:  # capture can fail on locked or headless sessions
        logger.warning('Screenshot failed: %s', exc)
        return None
