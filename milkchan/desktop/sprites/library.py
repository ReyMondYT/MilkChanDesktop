"""The built-in character plus characters the user imported."""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
import uuid
from pathlib import Path

from milkchan.desktop.sprites.character import Character, CharacterError
from milkchan.paths import get_assets_dir, get_user_data_dir

logger = logging.getLogger(__name__)

BUILT_IN = ''


def library_dir() -> Path:
    return get_user_data_dir() / 'characters'


def character_dir(character_id: str) -> Path:
    if character_id == BUILT_IN:
        return get_assets_dir() / 'characters' / 'milkchan'
    if not re.fullmatch(r'[0-9a-f]{32}', character_id):
        raise CharacterError(f'Invalid character id: {character_id!r}')
    return library_dir() / character_id


def list_characters() -> list[tuple[str, str]]:
    """(id, name) pairs, built-in first; unreadable folders are skipped."""
    found = [(BUILT_IN, Character(character_dir(BUILT_IN)).name)]
    if library_dir().is_dir():
        for path in sorted(library_dir().iterdir()):
            try:
                found.append((path.name, Character(character_dir(path.name)).name))
            except (CharacterError, OSError):
                continue
    return found


def load_character(character_id: str) -> Character:
    """The requested character, or the built-in one when it cannot be read."""
    try:
        return Character(character_dir(character_id))
    except (CharacterError, OSError) as exc:
        if character_id == BUILT_IN:
            raise
        logger.warning('Character %s unavailable, using the built-in one: %s', character_id, exc)
        return Character(character_dir(BUILT_IN))


def import_character(source: Path | str) -> str:
    """Validate a character folder and copy it into the library; return its id."""
    source = Path(source)
    Character(source).validate()
    library_dir().mkdir(parents=True, exist_ok=True)
    character_id = uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix='.import-', dir=library_dir()) as staging:
        copy = Path(staging) / 'character'
        shutil.copytree(source, copy, ignore=lambda folder, names: [
            name for name in names
            if name.startswith('.') or not (
                Path(folder, name).is_dir() or name.endswith('.png') or name == 'character.json'
            )
        ])
        Character(copy).validate()
        copy.rename(library_dir() / character_id)
    return character_id


def active_character() -> Character:
    from milkchan.core.config import get_config

    return load_character(get_config().get('character', BUILT_IN))
