import os
import datetime
import uuid
import time
import tempfile
from pathlib import Path
from typing import Optional, Tuple
from PIL import Image
import mss

RECORDINGS_DIR = Path(__file__).resolve().parent.parent / 'recordings'
TEMP_DIR = RECORDINGS_DIR / 'temp'
TEMP_DIR.mkdir(parents=True, exist_ok=True)


def downscale_image_for_upload(src_path: str, max_dim: int = 1200) -> Optional[str]:
    """
    Downscale an image to have its largest dimension <= max_dim while keeping aspect ratio.
    Writes to a temp file and returns its path. Caller is responsible for deleting.
    Returns original path if already small enough or on error.
    """
    if not src_path or not os.path.exists(src_path):
        return None
    try:
        with Image.open(src_path) as im:
            w, h = im.size
            max_current = max(w, h)
            if max_current <= max_dim:
                return src_path
            scale = max_dim / float(max_current)
            new_w = max(2, int(w * scale))
            new_h = max(2, int(h * scale))
            im2 = im.resize((new_w, new_h), Image.LANCZOS)
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.png', prefix='downscaled_', dir=os.path.dirname(src_path))
            tmp.close()
            im2.save(tmp.name, optimize=True)
            return tmp.name
    except Exception as ex:
        print(f"[downscale_image_for_upload] error: {ex}")
        return src_path


def take_screenshot(resize_factor: float = 1.0) -> Optional[Tuple[str, int, int]]:
    """
    Captures a full-screen screenshot and optionally downsizes it for faster inference.

    Returns: (temp_path, width, height) of the saved (possibly resized) image.
    """
    for attempt in range(3):
        try:
            with mss.mss() as sct:
                monitor = sct.monitors[1]
                sct_img = sct.grab(monitor)
                full_width, full_height = sct_img.size

                img = Image.frombytes('RGB', sct_img.size, sct_img.bgra, 'raw', 'BGRX')

                # Clamp resize_factor to [0.1, 1.0] for downscaling (or no scaling)
                try:
                    rf = float(resize_factor or 1.0)
                except Exception:
                    rf = 1.0
                rf = max(0.1, min(1.0, rf))

                if rf != 1.0:
                    new_w = max(2, int(full_width * rf)) & ~1  # even
                    new_h = max(2, int(full_height * rf)) & ~1
                    img = img.resize((new_w, new_h), Image.LANCZOS)
                    out_w, out_h = new_w, new_h
                else:
                    out_w, out_h = full_width, full_height

                # Use microseconds + random suffix to avoid collisions, and atomic write via rename
                ts = datetime.datetime.now().strftime('%Y%m%d-%H%M%S_%f')
                suffix = uuid.uuid4().hex[:6]
                final_path = str(TEMP_DIR / f'screenshot_{ts}_{suffix}.png')
                tmp_path = final_path + '.part'
                try:
                    # silently save temporary file
                    img.save(tmp_path, format='PNG', optimize=True)
                    # Ensure file is flushed to disk before rename on Windows
                    try:
                        fd = os.open(tmp_path, os.O_RDONLY)
                        os.close(fd)
                    except Exception:
                        pass
                    os.replace(tmp_path, final_path)
                finally:
                    # If something failed before rename, best-effort cleanup
                    try:
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)
                    except Exception:
                        pass
                return final_path, out_w, out_h
        except Exception as e:
            try:
                print(f"[screenshot.take_screenshot] attempt {attempt+1} error: {e}")
            except Exception:
                pass
            time.sleep(0.05 * (attempt + 1))
    return None