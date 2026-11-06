"""Where MilkChan keeps its files.

User data (imported characters, brain updates, an old database awaiting hand-over) lives in
``$XDG_DATA_HOME/milkchan`` and the editable config in
``$XDG_CONFIG_HOME/milkchan/config.json``. Without the XDG variables both
resolve beneath the home directory, on Windows too. Bundled assets are read in
place and never copied.
"""

import logging
import os
import shutil
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

APP_DIR_NAME = 'milkchan'
_HOME = Path(os.environ.get('HOME') or Path.home())
LEGACY_USER_DATA_DIR = _HOME / '.milkchan'


def _xdg_dir(env_name: str, default_relative: str) -> Path:
    value = os.environ.get(env_name)
    return Path(value).expanduser() if value else _HOME / default_relative


USER_DATA_DIR = _xdg_dir('XDG_DATA_HOME', '.local/share') / APP_DIR_NAME
USER_CONFIG_DIR = _xdg_dir('XDG_CONFIG_HOME', '.config') / APP_DIR_NAME
CONFIG_FILE = USER_CONFIG_DIR / 'config.json'
DB_FILE = USER_DATA_DIR / 'milkchan.db'

# Left behind by earlier versions: caches, a copied asset bundle, an unused
# FFmpeg download, temporary screenshots and backups that duplicated the API key.
_OBSOLETE = (
    USER_DATA_DIR / 'sprite_cache.pkl',
    USER_DATA_DIR / 'ffmpeg',
    USER_DATA_DIR / 'ffmpeg.exe',
    USER_DATA_DIR / 'assets',
    USER_DATA_DIR / 'recordings',
    USER_DATA_DIR / 'backups',
    USER_CONFIG_DIR / 'backups',
)


def get_user_data_dir() -> Path:
    return USER_DATA_DIR


def get_config_path() -> Path:
    return CONFIG_FILE


def get_db_path() -> Path:
    return DB_FILE


def get_assets_dir() -> Path:
    """Bundled, read-only assets (PyInstaller extracts them to _MEIPASS)."""
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / 'assets'
    return Path(__file__).parent / 'desktop' / 'assets'


def remove_obsolete_files() -> None:
    for path in _OBSOLETE:
        try:
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
            else:
                continue
            logger.info('Removed obsolete %s', path)
        except OSError as exc:
            logger.warning('Could not remove obsolete %s: %s', path, exc)


def migrate_legacy_user_data() -> bool:
    """Explicitly copy the old ~/.milkchan layout to the XDG paths; never deletes it."""
    if LEGACY_USER_DATA_DIR == USER_DATA_DIR or not LEGACY_USER_DATA_DIR.exists():
        return False
    copies = [(LEGACY_USER_DATA_DIR / 'config.json', CONFIG_FILE)]
    copies += [(LEGACY_USER_DATA_DIR / name, USER_DATA_DIR / name)
               for name in ('milkchan.db', 'updater_state.json', 'sentientmilk_framework')]
    try:
        for source, target in copies:
            if source.exists() and not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                if source.is_dir():
                    shutil.copytree(source, target)
                else:
                    shutil.copy2(source, target)
        return True
    except OSError as exc:
        logger.warning('Legacy user data migration failed: %s', exc)
        return False
