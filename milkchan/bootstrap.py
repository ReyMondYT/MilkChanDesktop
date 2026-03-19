"""
Bootstrap module - First-run setup for MilkChan

Creates ~/.milkchan folder and copies assets on first run.
Shows progress dialog during setup.
Pre-caches sprites for fast startup.
"""

import os
import sys
import shutil
import logging
import pickle
import urllib.request
import zipfile
import ssl
from pathlib import Path
from typing import Optional, Callable, Dict, Any

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# User data directory
USER_DATA_DIR = Path.home() / '.milkchan'

# Subdirectories
ASSETS_DIR = USER_DATA_DIR / 'assets'
SPRITES_DIR = ASSETS_DIR / 'sprites'
CONFIG_FILE = USER_DATA_DIR / 'config.json'
DB_FILE = USER_DATA_DIR / 'milkchan.db'
CACHE_FILE = USER_DATA_DIR / 'sprite_cache.pkl'
FFMPEG_FILE = USER_DATA_DIR / ('ffmpeg.exe' if sys.platform == 'win32' else 'ffmpeg')

# Basic sanity requirements to consider the asset install “complete”
REQUIRED_ASSET_FILES = (
    'MILKCHAN.md',
    'icon.png',
    'mappings.json',
)
MIN_SPRITE_FILES = 10  # any healthy install ships hundreds of sprites

# FFmpeg download URLs by platform
FFMPEG_DOWNLOAD_URLS = {
    'win32': "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
    'linux': "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz",
    'darwin': "https://evermeet.cx/ffmpeg/getrelease/zip",  # macOS
}

FFMPEG_DOWNLOAD_URL = FFMPEG_DOWNLOAD_URLS.get(sys.platform, FFMPEG_DOWNLOAD_URLS['linux'])


def get_user_data_dir() -> Path:
    """Get user data directory path"""
    return USER_DATA_DIR


def get_assets_dir() -> Path:
    """Get assets directory path"""
    return ASSETS_DIR


def get_config_path() -> Path:
    """Get config file path"""
    return CONFIG_FILE


def get_db_path() -> Path:
    """Get database file path"""
    return DB_FILE


def get_cache_file() -> Path:
    """Get sprite cache file path"""
    return CACHE_FILE


def get_ffmpeg_path() -> Path:
    """Get FFmpeg executable path"""
    return FFMPEG_FILE


def is_ffmpeg_installed() -> bool:
    """Check if FFmpeg is available (system PATH or user data)"""
    if shutil.which('ffmpeg'):
        return True
    return FFMPEG_FILE.exists()


def download_ffmpeg(
    progress_callback: Optional[Callable[[int, int, str], None]] = None
) -> bool:
    """
    Download FFmpeg to user data directory based on platform.

    Returns True if successful or already installed.
    """
    if FFMPEG_FILE.exists():
        logger.info("FFmpeg already downloaded")
        return True

    try:
        logger.info("Downloading FFmpeg...")
        print("[Bootstrap] Downloading FFmpeg...")
        
        # Determine file extension based on platform
        if sys.platform == 'win32':
            download_path = USER_DATA_DIR / 'ffmpeg.zip'
        else:
            download_path = USER_DATA_DIR / 'ffmpeg.tar.xz'

        # Create SSL context that doesn't verify certificates
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        https_handler = urllib.request.HTTPSHandler(context=ssl_context)
        opener = urllib.request.build_opener(https_handler)
        urllib.request.install_opener(opener)

        def report_hook(count: int, block_size: int, total_size: int):
            if progress_callback and total_size > 0:
                downloaded = count * block_size
                percent = int((downloaded / total_size) * 100)
                progress_callback(min(downloaded, total_size), total_size, f"Downloading FFmpeg: {percent}%")

        urllib.request.urlretrieve(FFMPEG_DOWNLOAD_URL, download_path, reporthook=report_hook)

        if progress_callback:
            progress_callback(0, 100, "Extracting FFmpeg...")

        # Extract based on platform
        if sys.platform == 'win32':
            # Windows: extract from zip
            with zipfile.ZipFile(download_path, 'r') as zf:
                ffmpeg_in_zip = None
                for name in zf.namelist():
                    if name.endswith('ffmpeg.exe'):
                        ffmpeg_in_zip = name
                        break
                
                if not ffmpeg_in_zip:
                    logger.error("ffmpeg.exe not found in downloaded zip")
                    return False
                
                zf.extract(ffmpeg_in_zip, USER_DATA_DIR)
                extracted_path = USER_DATA_DIR / ffmpeg_in_zip
                shutil.move(str(extracted_path), str(FFMPEG_FILE))
        else:
            # Linux/macOS: extract from tar.xz
            import tarfile
            with tarfile.open(download_path, 'r:xz') as tf:
                ffmpeg_in_tar = None
                for member in tf.getmembers():
                    if member.name.endswith('/ffmpeg') or member.name == 'ffmpeg':
                        ffmpeg_in_tar = member
                        break
                
                if not ffmpeg_in_tar:
                    logger.error("ffmpeg not found in downloaded archive")
                    return False
                
                tf.extract(ffmpeg_in_tar, USER_DATA_DIR)
                extracted_path = USER_DATA_DIR / ffmpeg_in_tar.name
                shutil.move(str(extracted_path), str(FFMPEG_FILE))
                # Make executable on Linux/macOS
                FFMPEG_FILE.chmod(0o755)

        # Cleanup
        if download_path.exists():
            download_path.unlink()

        for item in USER_DATA_DIR.iterdir():
            if item.is_dir() and item.name.startswith('ffmpeg-'):
                shutil.rmtree(item)

        logger.info(f"FFmpeg downloaded to {FFMPEG_FILE}")
        print(f"[Bootstrap] FFmpeg installed: {FFMPEG_FILE}")
        return True

    except Exception as e:
        logger.exception(f"FFmpeg download failed: {e}")
        print(f"[Bootstrap] FFmpeg download failed: {e}")
        return False


def get_bundled_assets_dir() -> Path:
    """Get bundled assets directory (works in both dev and frozen)"""
    if getattr(sys, 'frozen', False):
        # PyInstaller frozen
        base = Path(sys._MEIPASS)
        return base / 'assets'
    else:
        # Development
        return Path(__file__).parent / 'desktop' / 'assets'


def _has_valid_assets() -> bool:
    """Return True when the user data directory looks complete."""
    try:
        if not USER_DATA_DIR.exists():
            return False
        if not ASSETS_DIR.exists():
            return False
        if not SPRITES_DIR.exists():
            return False

        sprite_count = sum(1 for _ in SPRITES_DIR.rglob('*.png'))
        if sprite_count < MIN_SPRITE_FILES:
            return False

        for rel_path in REQUIRED_ASSET_FILES:
            if not (ASSETS_DIR / rel_path).exists():
                return False
    except Exception as exc:
        logger.warning(f"Asset validation failed: {exc}")
        return False
    return True


def is_first_run() -> bool:
    """Check if this is first run (user data dir doesn't exist or assets missing)"""
    return not _has_valid_assets()


def is_cache_valid() -> bool:
    """Check if sprite cache exists and is valid"""
    if not CACHE_FILE.exists():
        return False
    # Check if cache is newer than sprites
    if SPRITES_DIR.exists():
        cache_mtime = CACHE_FILE.stat().st_mtime
        for sprite_file in SPRITES_DIR.rglob('*.png'):
            if sprite_file.stat().st_mtime > cache_mtime:
                return False
    return True


def get_cache_resolution_scale() -> Optional[float]:
    """Get the resolution scale stored in cache, or None if no cache"""
    if not CACHE_FILE.exists():
        return None
    try:
        with open(CACHE_FILE, 'rb') as f:
            cache = pickle.load(f)
        return cache.get('resolution_scale', 1.0)
    except Exception:
        return None


def rebuild_sprite_cache(resolution_scale: float = 1.0) -> Dict[str, Any]:
    """Rebuild sprite cache with new resolution scale"""
    print(f"[Bootstrap] Rebuilding sprite cache with scale {resolution_scale}...")
    return _cache_sprites_with_progress(resolution_scale=resolution_scale)


def _copy_tree_with_progress(
    src: Path, 
    dst: Path, 
    progress_callback: Optional[Callable[[int, int, str], None]] = None
) -> int:
    """Copy directory tree with progress callback"""
    total_files = sum(1 for _ in src.rglob('*') if _.is_file())
    copied = 0
    
    for item in src.rglob('*'):
        rel_path = item.relative_to(src)
        dest_path = dst / rel_path
        
        if item.is_dir():
            dest_path.mkdir(parents=True, exist_ok=True)
        else:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest_path)
            copied += 1
            if progress_callback:
                progress_callback(copied, total_files, str(rel_path))
    
    return copied


def _cache_sprites_with_progress(
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    resolution_scale: float = 1.0
) -> Dict[str, Any]:
    """Pre-cache all sprites to pickle file (resized to display resolution)"""
    cache_data = {
        'sprites': {},
        'mappings': {},
        'resolution_scale': resolution_scale
    }
    
    # Load mappings
    mappings_file = ASSETS_DIR / 'mappings.json'
    if mappings_file.exists():
        import json
        with open(mappings_file, 'r', encoding='utf-8') as f:
            cache_data['mappings'] = json.load(f)
    else:
        # Scan sprites folder
        cache_data['mappings'] = _scan_sprites()
    
    # Count total sprites
    total = sum(1 for _ in SPRITES_DIR.rglob('*.png'))
    current = 0
    
    # Base display size (based on normalize_img in sprites.py)
    BASE_WIDTH = 685
    BASE_HEIGHT = 450
    
    # Use uniform scaling to avoid distortion
    # Original sprites are 1920x1080
    ORIG_WIDTH = 1920
    ORIG_HEIGHT = 1080
    # Fit into target size while maintaining aspect ratio
    scale = min(BASE_WIDTH / ORIG_WIDTH, BASE_HEIGHT / ORIG_HEIGHT) * resolution_scale
    display_width = int(ORIG_WIDTH * scale)
    display_height = int(ORIG_HEIGHT * scale)
    
    # Cache all sprites (resized)
    for sprite_file in SPRITES_DIR.rglob('*.png'):
        try:
            rel_path = sprite_file.relative_to(SPRITES_DIR)
            parts = rel_path.parts
            if len(parts) >= 3:
                pose, mood = parts[0], parts[1]
                filename = sprite_file.stem
                cache_key = f"{pose}_{mood}_{filename}"
                
                img = Image.open(sprite_file).convert('RGBA')
                # Resize using NEAREST for pixel art (preserves sharp edges)
                img = img.resize((display_width, display_height), Image.Resampling.NEAREST)
                cache_data['sprites'][cache_key] = np.array(img)
                
                current += 1
                if progress_callback:
                    progress_callback(current, total, str(rel_path))
        except Exception as e:
            logger.warning(f"Failed to cache {sprite_file}: {e}")
    
    # Save cache
    with open(CACHE_FILE, 'wb') as f:
        pickle.dump(cache_data, f)
    
    return cache_data


def _scan_sprites() -> Dict:
    """Scan sprites folder and return mappings"""
    import re
    expressions = {}
    if not SPRITES_DIR.exists():
        return expressions
    
    for pose in os.listdir(SPRITES_DIR):
        pose_path = SPRITES_DIR / pose
        if not pose_path.is_dir() or pose.startswith('.'):
            continue
        expressions[pose] = {}
        for mood in os.listdir(pose_path):
            mood_path = pose_path / mood
            if not mood_path.is_dir() or mood.startswith('.'):
                continue
            expressions[pose][mood] = []
            for file in os.listdir(mood_path):
                if file.endswith('.png'):
                    expressions[pose][mood].append(file[:-4])
    
    # Save mappings
    import json
    with open(ASSETS_DIR / 'mappings.json', 'w', encoding='utf-8') as f:
        json.dump(expressions, f, indent=4)
    
    return expressions


def load_sprite_cache() -> Optional[Dict[str, Any]]:
    """Load sprite cache if valid, return None if needs rebuild"""
    if not is_cache_valid():
        return None
    try:
        with open(CACHE_FILE, 'rb') as f:
            return pickle.load(f)
    except Exception as e:
        logger.warning(f"Failed to load sprite cache: {e}")
        return None


def setup_user_data(
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    force: bool = False
) -> bool:
    """
    Setup user data directory.
    
    Args:
        progress_callback: Function called with (current, total, filename)
        force: Force re-copy even if exists
    
    Returns:
        True if successful
    """
    try:
        # Create main directory
        USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        
        # Create subdirectories
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        SPRITES_DIR.mkdir(parents=True, exist_ok=True)
        
        # Get bundled assets
        bundled = get_bundled_assets_dir()
        
        if not bundled.exists():
            logger.error(f"Bundled assets not found at {bundled}")
            return False
        
        # Copy assets
        logger.info(f"Copying assets from {bundled} to {ASSETS_DIR}")
        
        # Copy each top-level item
        total_items = sum(1 for _ in bundled.iterdir()) + sum(1 for _ in (bundled / 'sprites').rglob('*') if _.is_file())
        current = 0
        
        for item in bundled.iterdir():
            if item.name == 'sprites':
                # Copy sprites folder with progress
                current = _copy_tree_with_progress(
                    item, SPRITES_DIR, 
                    lambda c, t, f: progress_callback(c, t, f) if progress_callback else None
                )
            else:
                # Copy other files
                dest = ASSETS_DIR / item.name
                if item.is_file():
                    if not dest.exists() or force:
                        shutil.copy2(item, dest)
                    current += 1
                    if progress_callback:
                        progress_callback(current, total_items, item.name)
        
        # Cache sprites
        logger.info("Caching sprites...")
        _cache_sprites_with_progress(
            lambda c, t, f: progress_callback(current + c, total_items + t, f"cache: {f}") if progress_callback else None
        )

        # Always download FFmpeg for self-contained setup
        if not FFMPEG_FILE.exists():
            logger.info("Downloading FFmpeg...")
            if progress_callback:
                progress_callback(0, 100, "Downloading FFmpeg...")
            if not download_ffmpeg(progress_callback):
                logger.warning("FFmpeg download failed, vision features may require system FFmpeg")

        logger.info(f"Setup complete: {USER_DATA_DIR}")
        return True
        
    except Exception as e:
        logger.exception(f"Setup failed: {e}")
        return False


def check_framework_update_on_first_run() -> bool:
    """Check for framework updates on first run and ask user
    
    Returns:
        True if update was applied or not needed, False if user rejected
    """
    from milkchan.core.updater import AutoUpdater
    
    updater = AutoUpdater(auto_check=False)
    
    # Check for updates
    info = updater.check_for_updates(force=True)
    
    if not info or not info.available:
        logger.info("No framework updates available")
        return True
    
    # Check if user already rejected this specific version
    state = updater._load_state()
    rejected_sha = state.get('update_rejected', '')
    if rejected_sha == info.latest_sha:
        logger.info(f"User previously rejected update {info.latest_sha[:7]}, skipping")
        return True
    
    # Show dialog asking user
    from PyQt5.QtWidgets import QApplication, QMessageBox
    
    app = QApplication.instance()
    if app is None:
        return True
    
    message = (
        f"A framework update is available!\n\n"
        f"Version: {info.latest_sha[:7]}\n"
        f"Released: {info.commit_date[:10]}\n\n"
        f"This update may include bug fixes and improvements.\n\n"
        f"Would you like to download it now?"
    )
    
    reply = QMessageBox.question(
        None,
        'Framework Update Available',
        message,
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.Yes
    )
    
    if reply == QMessageBox.Yes:
        logger.info("User accepted framework update")
        success = updater.apply_update(backup=True)
        if success:
            QMessageBox.information(
                None,
                'Update Complete',
                'Framework updated successfully!\n\nThe application will now restart.'
            )
            return True
        else:
            QMessageBox.warning(
                None,
                'Update Failed',
                'Failed to apply update. Check logs for details.'
            )
            return True
    else:
        logger.info("User rejected framework update")
        # Save rejection so we don't ask again for this version
        state['update_rejected'] = info.latest_sha
        updater._save_state(state)
        return True


def run_setup_dialog() -> bool:
    """Run setup with Qt progress dialog"""
    from PyQt5.QtWidgets import QProgressDialog, QApplication, QMessageBox
    from PyQt5.QtCore import Qt, QTimer
    
    if not is_first_run():
        logger.info("User data already exists, skipping setup")
        return True
    
    # Ensure QApplication exists
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    
    # Create progress dialog
    dialog = QProgressDialog("Setting up MilkChan...", "Cancel", 0, 100)
    dialog.setWindowTitle("MilkChan Setup")
    dialog.setWindowModality(Qt.ApplicationModal)
    dialog.setAutoClose(True)
    dialog.setMinimumDuration(0)
    dialog.setValue(0)
    
    # Force show
    dialog.show()
    QApplication.processEvents()
    
    # Count total files
    bundled = get_bundled_assets_dir()
    total_files = sum(1 for _ in bundled.rglob('*') if _.is_file()) * 2  # Copy + cache
    
    copied = [0]
    
    def on_progress(current: int, total: int, filename: str):
        copied[0] = current
        percent = int((current / total) * 100) if total > 0 else 0
        dialog.setValue(min(percent, 99))  # Cap at 99 until done
        dialog.setLabelText(f"Copying: {filename[:30]}...")
        QApplication.processEvents()
    
    # Run setup
    success = setup_user_data(progress_callback=on_progress)
    
    if success:
        dialog.setValue(100)
        dialog.setLabelText("Setup complete!")
        QApplication.processEvents()
        QTimer.singleShot(500, dialog.close)
        QApplication.processEvents()
        
        # Check for framework updates on first run
        if getattr(sys, 'frozen', False):
            # Only show update dialog for bundled EXE
            check_framework_update_on_first_run()
    else:
        dialog.close()
    
    return success


def ensure_setup() -> bool:
    """Ensure user data is set up, run dialog if needed"""
    if is_first_run():
        return run_setup_dialog()
    
    if not is_cache_valid():
        print("[Bootstrap] Rebuilding sprite cache...")
        _cache_sprites_with_progress()
    if not FFMPEG_FILE.exists():
        print("[Bootstrap] FFmpeg not in user data, downloading...")
        download_ffmpeg()
    return True