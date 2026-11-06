"""Character sprite format: one body per pose plus small face layers.

Every PNG of a character uses the same canvas size, so layers line up without
coordinates. Layout::

    <character>/
      character.json               optional: {"name": "...", "faces": {"one_arm": "arms_down"}}
      <pose>/body.png              required, drawn with the neutral resting face
      <pose>/<state>.png           optional, shared by every mood of the pose
      <pose>/<mood>/face.png       resting face of the mood (neutral uses the body's face)
      <pose>/<mood>/face_<n>.png   extra idle variants such as glances, n >= 2
      <pose>/<mood>/<state>.png    mood-specific state; <state>_<n>.png for variant n
      <pose>/<mood>/body.png       optional: the mood changes the body (body_<n>.png per variant)

States are ``eyes_half`` (thinking), ``eyes_closed`` (blink), ``mouth_half`` and
``mouth_full`` (talking). A missing layer falls back from variant to mood to
pose, and otherwise is simply not drawn. ``faces`` lets a pose reuse the mood
folders and shared states of another pose with the same head position.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from PIL import Image

DEFAULT_MOOD = 'neutral'
EYE_STATES = ('eyes_half', 'eyes_closed')
MOUTH_STATES = ('mouth_half', 'mouth_full')
STATES = EYE_STATES + MOUTH_STATES

_MOOD_LAYER = re.compile(
    r'(?P<slot>body|face|eyes_half|eyes_closed|mouth_half|mouth_full)(?:_(?P<variant>[2-9]|[1-9]\d+))?'
)
_POSE_LAYERS = frozenset(('body',) + STATES)
_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]*')


class CharacterError(ValueError):
    """The folder does not follow the character layout."""


@dataclass(frozen=True)
class Slots:
    """The layers drawn for one pose, mood and variant, bottom to top."""

    body: Path
    face: Path | None
    states: dict[str, Path]

    def paths(self, *states: str | None) -> list[Path]:
        layers = [self.body, self.face, *(self.states.get(state) for state in states if state)]
        return [path for path in layers if path is not None]


@dataclass(frozen=True)
class Frame:
    """The box, in canvas pixels, around everything any body shows."""

    left: int
    top: int
    width: int
    height: int


def _png_layers(folder: Path) -> dict[str, Path]:
    return {path.stem: path for path in folder.glob('*.png') if path.is_file()}


def _subfolders(folder: Path) -> list[Path]:
    return sorted(path for path in folder.iterdir() if path.is_dir() and not path.name.startswith('.'))


def _check_name(kind: str, name: str) -> None:
    if not _NAME.fullmatch(name):
        raise CharacterError(f'{kind} name "{name}" may only use letters, digits, "_" and "-"')


class Character:
    """Read a character folder; image data is loaded only when rendered."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        if not self.root.is_dir():
            raise CharacterError(f'Character folder not found: {self.root}')
        meta = self._read_meta()
        self.name = str(meta.get('name') or self.root.name)
        pose_files, mood_files = self._scan()
        faces = self._face_owners(meta.get('faces') or {}, pose_files, mood_files)
        self._slots = {
            pose: self._resolve(pose, faces.get(pose, pose), pose_files, mood_files)
            for pose in pose_files
        }

    def _read_meta(self) -> dict:
        path = self.root / 'character.json'
        if not path.exists():
            return {}
        try:
            meta = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise CharacterError(f'character.json is not valid JSON: {exc}') from exc
        if not isinstance(meta, dict) or not isinstance(meta.get('faces', {}), dict):
            raise CharacterError('character.json must be an object; "faces" maps pose to pose')
        return meta

    def _scan(self):
        pose_files: dict[str, dict[str, Path]] = {}
        mood_files: dict[str, dict[str, dict[str, Path]]] = {}
        for pose_dir in _subfolders(self.root):
            pose = pose_dir.name
            _check_name('Pose', pose)
            files = _png_layers(pose_dir)
            unknown = sorted(set(files) - _POSE_LAYERS)
            if unknown:
                raise CharacterError(
                    f'{pose}/{unknown[0]}.png: pose folders may contain only body.png and '
                    f'{", ".join(STATES)}'
                )
            if 'body' not in files:
                raise CharacterError(f'{pose}/body.png is missing')
            pose_files[pose] = files
            mood_files[pose] = {}
            for mood_dir in _subfolders(pose_dir):
                _check_name('Mood', mood_dir.name)
                layers = _png_layers(mood_dir)
                for stem in layers:
                    if not _MOOD_LAYER.fullmatch(stem):
                        raise CharacterError(
                            f'{pose}/{mood_dir.name}/{stem}.png: use face, body or a state name '
                            f'({", ".join(STATES)}), optionally ending in _2, _3, …'
                        )
                mood_files[pose][mood_dir.name] = layers
        if not pose_files:
            raise CharacterError('No pose folders with a body.png were found')
        return pose_files, mood_files

    @staticmethod
    def _face_owners(faces: dict, pose_files, mood_files) -> dict[str, str]:
        for pose, owner in faces.items():
            if pose not in pose_files or owner not in pose_files:
                raise CharacterError(f'"faces": {pose} -> {owner} must name existing poses')
            if owner in faces:
                raise CharacterError(f'"faces": {owner} borrows faces itself; point {pose} at its owner')
            if set(pose_files[pose]) != {'body'}:
                raise CharacterError(f'{pose} borrows faces from {owner}, so it may only contain body.png')
            for mood, layers in mood_files[pose].items():
                if mood not in mood_files[owner] or any(
                    _MOOD_LAYER.fullmatch(stem)['slot'] != 'body' for stem in layers
                ):
                    raise CharacterError(
                        f'{pose}/{mood}: a pose that borrows faces may only override bodies '
                        f'of moods that {owner} has'
                    )
        return dict(faces)

    @staticmethod
    def _resolve(pose: str, owner: str, pose_files, mood_files) -> dict[str, list[Slots]]:
        resolved = {}
        moods = [DEFAULT_MOOD, *sorted(set(mood_files[owner]) - {DEFAULT_MOOD})]
        for mood in moods:
            face_layers = mood_files[owner].get(mood, {})
            body_layers = mood_files[pose].get(mood, {})
            numbers = {1}
            for stem in (*face_layers, *body_layers):
                match = _MOOD_LAYER.fullmatch(stem)
                if match['variant'] and match['slot'] in ('face', 'body'):
                    numbers.add(int(match['variant']))
            variants = []
            for variant in sorted(numbers):
                suffix = '' if variant == 1 else f'_{variant}'
                states = {}
                for state in STATES:
                    path = (face_layers.get(state + suffix) or face_layers.get(state)
                            or pose_files[owner].get(state))
                    if path:
                        states[state] = path
                variants.append(Slots(
                    body=(body_layers.get('body' + suffix) or body_layers.get('body')
                          or pose_files[pose]['body']),
                    face=face_layers.get('face' + suffix),
                    states=states,
                ))
            resolved[mood] = variants
        return resolved

    def moods(self) -> dict[str, list[str]]:
        """Pose name -> available moods, neutral first."""
        return {pose: list(moods) for pose, moods in self._slots.items()}

    def variant_count(self, pose: str, mood: str) -> int:
        return len(self._slots[pose][mood])

    def slots(self, pose: str, mood: str, variant: int = 1) -> Slots:
        return self._slots[pose][mood][variant - 1]

    def all_paths(self) -> set[Path]:
        return {
            path
            for moods in self._slots.values()
            for variants in moods.values()
            for slots in variants
            for path in slots.paths(*STATES)
        }

    def validate(self) -> Frame:
        """Check image sizes and visibility; layout is checked on construction."""
        sizes = {}
        for path in sorted(self.all_paths()):
            with Image.open(path) as image:
                sizes.setdefault(image.size, path)
        if len(sizes) > 1:
            (first, a), (second, b) = list(sizes.items())[:2]
            raise CharacterError(
                f'All PNGs must share one canvas size: {a.relative_to(self.root)} is '
                f'{first[0]}×{first[1]}, {b.relative_to(self.root)} is {second[0]}×{second[1]}'
            )
        return self.frame

    @cached_property
    def frame(self) -> Frame:
        boxes = []
        bodies = {slots.body for moods in self._slots.values() for v in moods.values() for slots in v}
        for path in sorted(bodies):
            with Image.open(path) as image:
                box = image.convert('RGBA').getchannel('A').getbbox()
            if box is None:
                raise CharacterError(f'{path.relative_to(self.root)} has no visible pixels')
            boxes.append(box)
        left, top = min(b[0] for b in boxes), min(b[1] for b in boxes)
        return Frame(left, top, max(b[2] for b in boxes) - left, max(b[3] for b in boxes) - top)


def load_layer(path: Path) -> tuple[Image.Image, int, int] | None:
    """Visible part of a layer and its canvas position; None when it is empty."""
    with Image.open(path) as source:
        image = source.convert('RGBA')
    box = image.getchannel('A').getbbox()
    if box is None:
        return None
    return image.crop(box), box[0], box[1]


def scale_layer(image: Image.Image, x: int, y: int, scale: float) -> tuple[Image.Image, int, int]:
    """Scale a layer placed at (x, y) exactly as scaling the whole canvas would.

    Upscaling first repeats pixels by a whole factor (crisp pixel art), then
    every step down averages area on the shared output grid, so separately
    scaled layers still line up with each other.
    """
    if scale <= 0:
        raise ValueError('scale must be positive')
    factor = math.ceil(scale) if scale > 1 else 1
    if factor > 1:
        image = image.resize((image.width * factor, image.height * factor), Image.Resampling.NEAREST)
        x, y, scale = x * factor, y * factor, scale / factor
    left, top = math.floor(x * scale), math.floor(y * scale)
    right = math.ceil((x + image.width) * scale)
    bottom = math.ceil((y + image.height) * scale)
    # Transparent margin: output pixels on the edges sample a little outside the layer.
    pad = math.ceil(1 / scale)
    padded = Image.new('RGBA', (image.width + 2 * pad, image.height + 2 * pad))
    padded.paste(image, (pad, pad))
    box = (
        left / scale - x + pad,
        top / scale - y + pad,
        right / scale - x + pad,
        bottom / scale - y + pad,
    )
    scaled = padded.resize((right - left, bottom - top), Image.Resampling.BOX, box=box)
    return scaled, left, top
