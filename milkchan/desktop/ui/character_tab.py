"""Settings page: choose, import and preview characters."""

from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from milkchan.desktop.sprites.character import Character, CharacterError
from milkchan.desktop.sprites.library import (
    BUILT_IN,
    character_dir,
    import_character,
    list_characters,
)
from milkchan.desktop.sprites.renderer import SpriteRenderer

PREVIEW_HEIGHT = 300
FRAME_MS = 120
MODES = ('Still', 'Blink', 'Talk', 'Think')


class ImportWorker(QThread):
    imported = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, folder: str, parent):
        super().__init__(parent)
        self.folder = folder

    def run(self):
        try:
            self.imported.emit(import_character(self.folder))
        except (CharacterError, OSError) as exc:
            self.failed.emit(str(exc))


class CharacterTab(QWidget):
    def __init__(self, config: dict):
        super().__init__()
        self.renderer = None
        self.worker = None
        self._tick = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._advance)

        self.characters = QListWidget()
        self.characters.currentItemChanged.connect(self._show_character)
        self.import_btn = QPushButton("Import folder…")
        self.import_btn.clicked.connect(self._choose_folder)
        self.status = QLabel("")
        self.status.setObjectName("statusLabel")
        self.status.setWordWrap(True)

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(PREVIEW_HEIGHT, PREVIEW_HEIGHT)
        self.pose_combo = QComboBox()
        self.pose_combo.currentTextChanged.connect(self._show_pose)
        self.mood_combo = QComboBox()
        self.mood_combo.currentTextChanged.connect(self._show_mood)
        self.variant_spin = QSpinBox()
        self.variant_spin.setMinimum(1)
        self.variant_spin.valueChanged.connect(self._render)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(MODES)
        self.mode_combo.currentTextChanged.connect(self._set_mode)

        left = QVBoxLayout()
        left.addWidget(self.characters, 1)
        left.addWidget(self.import_btn)
        left.addWidget(self.status)
        controls = QFormLayout()
        controls.addRow("Pose", self.pose_combo)
        controls.addRow("Mood", self.mood_combo)
        controls.addRow("Variant", self.variant_spin)
        controls.addRow("Animation", self.mode_combo)
        right = QVBoxLayout()
        right.addWidget(self.preview, 1)
        right.addLayout(controls)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addLayout(left, 1)
        layout.addLayout(right, 1)

        self._populate(config.get("character", BUILT_IN))

    def _populate(self, selected: str):
        self.characters.clear()
        for character_id, name in list_characters():
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, character_id)
            self.characters.addItem(item)
            if character_id == selected:
                self.characters.setCurrentItem(item)
        if self.characters.currentItem() is None:
            self.characters.setCurrentRow(0)

    def _show_character(self, item):
        self.renderer = None
        self.pose_combo.clear()
        if item is None:
            return
        try:
            character = Character(character_dir(item.data(Qt.UserRole)))
            character.validate()
        except (CharacterError, OSError) as exc:
            self.preview.clear()
            self.status.setText(str(exc))
            return
        self.status.setText("")
        self.renderer = SpriteRenderer(character, PREVIEW_HEIGHT)
        self.pose_combo.addItems(list(character.moods()))

    def _show_pose(self, pose: str):
        self.mood_combo.clear()
        if self.renderer and pose:
            self.mood_combo.addItems(self.renderer.character.moods()[pose])

    def _show_mood(self, mood: str):
        if not (self.renderer and mood):
            return
        pose = self.pose_combo.currentText()
        self.renderer.retain(pose, mood)
        self.variant_spin.setMaximum(self.renderer.character.variant_count(pose, mood))
        self.variant_spin.setValue(1)
        self._render()

    def _set_mode(self, mode: str):
        self._tick = 0
        if mode in ('Blink', 'Talk'):
            self.timer.start(FRAME_MS)
        else:
            self.timer.stop()
        self._render()

    def _advance(self):
        self._tick += 1
        self._render()

    def _render(self):
        pose, mood = self.pose_combo.currentText(), self.mood_combo.currentText()
        if not (self.renderer and pose and mood):
            return
        mode = self.mode_combo.currentText()
        eyes = mouth = None
        if mode == 'Blink' and self._tick % 8 == 0:
            eyes = 'eyes_closed'
        elif mode == 'Think':
            eyes = 'eyes_half'
        elif mode == 'Talk':
            mouth = 'mouth_full' if self._tick % 2 else 'mouth_half'
        self.preview.setPixmap(self.renderer.render(pose, mood, self.variant_spin.value(), eyes, mouth))

    def _choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose a character folder")
        if not folder:
            return
        self.import_btn.setEnabled(False)
        self.status.setText("Checking and importing…")
        self.worker = ImportWorker(folder, self)
        self.worker.imported.connect(self._imported)
        self.worker.failed.connect(self._import_failed)
        self.worker.finished.connect(self._import_finished)
        self.worker.start()

    def _imported(self, character_id: str):
        self._populate(character_id)
        self.status.setText(f"Imported {self.characters.currentItem().text()}.")

    def _import_failed(self, message: str):
        self.status.setText(f"Not imported: {message}")

    def _import_finished(self):
        self.worker = None
        self.import_btn.setEnabled(True)

    def is_busy(self) -> bool:
        return self.worker is not None

    def save_values(self, cfg: dict):
        item = self.characters.currentItem()
        if item is not None:
            cfg["character"] = item.data(Qt.UserRole)
