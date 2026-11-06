"""Draw a character state as a QPixmap: scaled layers painted bottom to top."""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QImage, QPainter, QPixmap

from milkchan.desktop.sprites.character import STATES, Character, load_layer, scale_layer

BASE_HEIGHT = 370  # on-screen character height at 100 % scale, as Milk Chan was always shown


def to_pixmap(image: Image.Image) -> QPixmap:
    data = image.tobytes('raw', 'RGBA')
    return QPixmap.fromImage(
        QImage(data, image.width, image.height, image.width * 4, QImage.Format_RGBA8888)
    )


class SpriteRenderer:
    """Keeps only the scaled layers of the current pose and mood in memory."""

    def __init__(self, character: Character, height: int):
        self.character = character
        frame = character.frame
        self._scale = height / frame.height
        self.size = QSize(max(1, round(frame.width * self._scale)), height)
        self._layers: dict[Path, tuple[QPixmap, int, int] | None] = {}

    def _layer(self, path: Path) -> tuple[QPixmap, int, int] | None:
        if path not in self._layers:
            loaded = load_layer(path)
            if loaded is None:
                self._layers[path] = None
            else:
                image, x, y = loaded
                frame = self.character.frame
                scaled, left, top = scale_layer(image, x - frame.left, y - frame.top, self._scale)
                self._layers[path] = (to_pixmap(scaled), left, top)
        return self._layers[path]

    def render(self, pose: str, mood: str, variant: int = 1,
               eyes: str | None = None, mouth: str | None = None) -> QPixmap:
        pixmap = QPixmap(self.size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        for path in self.character.slots(pose, mood, variant).paths(eyes, mouth):
            layer = self._layer(path)
            if layer is not None:
                painter.drawPixmap(layer[1], layer[2], layer[0])
        painter.end()
        return pixmap

    def retain(self, pose: str, mood: str) -> None:
        """Forget layers that the given expression never draws."""
        keep = {
            path
            for variant in range(1, self.character.variant_count(pose, mood) + 1)
            for path in self.character.slots(pose, mood, variant).paths(*STATES)
        }
        self._layers = {path: layer for path, layer in self._layers.items() if path in keep}
