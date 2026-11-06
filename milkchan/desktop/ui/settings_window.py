"""MilkChan's native settings control panel."""

import copy
import sys

from PyQt5.QtCore import QSize, Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QFontDatabase
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from milkchan.desktop.ui.character_tab import CharacterTab
from milkchan.paths import get_assets_dir

FONT_PATH = str(get_assets_dir() / "Retro Gaming.ttf")

ACCENT = "#c4474d"
ACCENT_HOVER = "#db5960"
TEAL = "#28b9b1"
CREAM = "#f0dfbd"
BG = "#090a10"
SURFACE = "#10111a"
SURFACE_RAISED = "#171925"
BORDER = "#292b3b"
FG = "#eee9df"
MUTED = "#9798a8"


class ModelFetchWorker(QThread):
    """Ask the brain for the provider's models without blocking the UI."""

    models_ready = pyqtSignal(list)

    def __init__(self, api_key: str, base_url: str, parent=None):
        super().__init__(parent)
        self.api_key = api_key
        self.base_url = base_url

    def run(self):
        from milkchan.desktop.services import brain

        try:
            models = brain.client().models(self.base_url or None, self.api_key or None)
        except brain.BrainError:
            models = []
        self.models_ready.emit(models)


def load_retro_font() -> str:
    family = "Arial"
    try:
        fid = QFontDatabase.addApplicationFont(FONT_PATH)
        fams = QFontDatabase.applicationFontFamilies(fid)
        if fams:
            family = fams[0]
    except Exception:
        pass
    return family


class SettingsWindow(QDialog):
    """Edits MilkChan's own settings and, for the brain, ``brain = {'config', 'persona'}``."""

    def __init__(self, parent: QWidget, config: dict, brain: dict):
        super().__init__(parent)
        self.setWindowTitle("Milk Chan Settings")
        self.setModal(True)
        self.setMinimumSize(900, 620)
        self.resize(980, 680)

        self.original_config = copy.deepcopy(config)
        self.original_brain = copy.deepcopy(brain["config"])
        persona = brain["persona"]
        self.result_config = None
        self.result_brain = None
        self.result_persona = None

        self.font_family = load_retro_font()
        base_font = QFont("Segoe UI")
        base_font.setPixelSize(14)
        self.setFont(base_font)

        self._build_ui()
        self._load_values(config, persona)
        self._apply_style()

    def showEvent(self, event):
        super().showEvent(event)
        if sys.platform == "win32":
            try:
                import ctypes

                enabled = ctypes.c_int(1)
                hwnd = int(self.winId())
                # 20 is the supported immersive-dark-mode attribute on current Windows;
                # 19 covers earlier Windows 10 revisions.
                result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, 20, ctypes.byref(enabled), ctypes.sizeof(enabled)
                )
                if result:
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd, 19, ctypes.byref(enabled), ctypes.sizeof(enabled)
                    )
            except Exception:
                pass

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(18)

        header = QHBoxLayout()
        header.setSpacing(14)
        mark = QLabel("MC")
        mark.setObjectName("brandMark")
        mark.setAlignment(Qt.AlignCenter)
        mark.setFixedSize(48, 48)
        header.addWidget(mark)
        title_column = QVBoxLayout()
        title_column.setSpacing(1)
        eyebrow = QLabel("MILK CHAN  /  SYSTEM")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("Settings")
        title.setObjectName("title")
        subtitle = QLabel("Tune the assistant without losing her personality.")
        subtitle.setObjectName("subtitle")
        title_column.addWidget(eyebrow)
        title_column.addWidget(title)
        title_column.addWidget(subtitle)
        header.addLayout(title_column)
        header.addStretch()
        status = QLabel("●  LOCAL DESKTOP")
        status.setObjectName("localStatus")
        header.addWidget(status, 0, Qt.AlignTop)
        layout.addLayout(header)

        # Create tab pages
        self.api_tab = APITab(self.original_brain["defaults"])
        self.desktop_tab = DesktopTab(self.original_config)
        self.character_tab = CharacterTab(self.original_config)
        self.vision_tab = VisionTab(self.original_config)
        self.proactive_tab = ProactiveTab(self.original_config)
        self.tools_tab = ToolsTab()

        self.persona_edit = QTextEdit()
        self.persona_edit.setPlaceholderText("Describe the character's personality and behavior...")
        persona_page = QWidget()
        persona_layout = QVBoxLayout(persona_page)
        persona_layout.setContentsMargins(18, 18, 18, 18)
        persona_layout.addWidget(self.persona_edit)

        content = QHBoxLayout()
        content.setSpacing(16)
        nav_frame = QFrame()
        nav_frame.setObjectName("navigationFrame")
        nav_frame.setFixedWidth(190)
        nav_layout = QVBoxLayout(nav_frame)
        nav_layout.setContentsMargins(8, 10, 8, 10)
        nav_layout.setSpacing(4)
        nav_label = QLabel("CONTROL PANEL")
        nav_label.setObjectName("navLabel")
        nav_layout.addWidget(nav_label)
        self.navigation = QListWidget()
        self.navigation.setObjectName("settingsNavigation")
        self.navigation.setFocusPolicy(Qt.NoFocus)
        nav_layout.addWidget(self.navigation, 1)
        content.addWidget(nav_frame)

        self.pages = QStackedWidget()
        self.pages.setObjectName("settingsPages")
        page_specs = [
            ("01", "Connection", "Provider, credentials and model", self.api_tab),
            ("02", "Tools", "External services and capabilities", self.tools_tab),
            ("03", "Desktop", "Scale, motion and placement", self.desktop_tab),
            ("04", "Vision", "Screenshot context controls", self.vision_tab),
            ("05", "Proactive", "Background awareness timing", self.proactive_tab),
            ("06", "Persona", "Voice, temperament and behavior", persona_page),
            ("07", "Character", "Choose, import and preview characters", self.character_tab),
        ]
        for number, name, description, page in page_specs:
            item = QListWidgetItem(f"{number}   {name.upper()}")
            item.setToolTip(description)
            item.setSizeHint(item.sizeHint().expandedTo(QSize(0, 48)))
            self.navigation.addItem(item)
            self.pages.addWidget(self._wrap_page(name, description, page))
        self.navigation.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.navigation.setCurrentRow(0)
        content.addWidget(self.pages, 1)
        layout.addLayout(content, 1)

        # Buttons
        buttons = QHBoxLayout()
        footer_note = QLabel("Changes are applied when you save.")
        footer_note.setObjectName("footerNote")
        buttons.addWidget(footer_note)
        buttons.addStretch(1)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("secondaryButton")
        self.save_btn = QPushButton("Save")
        self.save_btn.setObjectName("primaryButton")
        self.save_btn.setDefault(True)
        buttons.addWidget(self.cancel_btn)
        buttons.addWidget(self.save_btn)
        layout.addLayout(buttons)

        self.cancel_btn.clicked.connect(self.reject)
        self.save_btn.clicked.connect(self._on_save)

    def _wrap_page(self, title: str, description: str, content: QWidget) -> QWidget:
        page = QFrame()
        page.setObjectName("pageCard")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(22, 20, 22, 20)
        page_layout.setSpacing(4)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        detail = QLabel(description)
        detail.setObjectName("pageDescription")
        page_layout.addWidget(heading)
        page_layout.addWidget(detail)
        divider = QFrame()
        divider.setObjectName("pageDivider")
        divider.setFrameShape(QFrame.HLine)
        page_layout.addWidget(divider)
        page_layout.addWidget(content, 1)
        return page

    def _apply_style(self):
        self.setStyleSheet(f"""
QDialog {{
    background: {BG};
    color: {FG};
}}
QLabel {{ color: {FG}; background: transparent; }}
QLabel#brandMark {{
    color: {CREAM}; background: {ACCENT}; border-radius: 12px;
    font-family: "{self.font_family}"; font-size: 15px; font-weight: 700;
}}
QLabel#eyebrow {{ color: {ACCENT}; font-family: "{self.font_family}"; font-size: 9px; }}
QLabel#title {{
    color: {CREAM}; font-family: "{self.font_family}"; font-size: 22px; font-weight: 700;
}}
QLabel#subtitle, QLabel#pageDescription, QLabel#footerNote {{ color: {MUTED}; }}
QLabel#localStatus {{ color: {TEAL}; font-size: 11px; font-weight: 600; padding-top: 5px; }}
QFrame#navigationFrame, QFrame#pageCard {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px;
}}
QLabel#navLabel {{ color: #676979; font-size: 10px; font-weight: 700; padding: 7px 10px 9px; }}
QListWidget#settingsNavigation {{ background: transparent; border: none; outline: none; }}
QListWidget#settingsNavigation::item {{
    color: #b6b4ba; border: none; border-radius: 7px; padding: 0 11px;
}}
QListWidget#settingsNavigation::item:selected {{
    background: #28171e; color: {CREAM}; border-left: 3px solid {ACCENT};
}}
QListWidget#settingsNavigation::item:hover:!selected {{ background: {SURFACE_RAISED}; color: {FG}; }}
QStackedWidget#settingsPages {{ background: transparent; }}
QLabel#pageTitle {{
    color: {CREAM}; font-family: "{self.font_family}"; font-size: 16px; font-weight: 700;
}}
QFrame#pageDivider {{ color: {BORDER}; background: {BORDER}; border: none; max-height: 1px; margin: 13px 0 5px; }}
QWidget {{ font-family: "Segoe UI", sans-serif; font-size: 13px; }}
QWidget:disabled {{ color: #606171; }}
QFormLayout QLabel {{ color: #cbc7c1; font-weight: 500; }}
QTextEdit, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {SURFACE_RAISED}; color: {FG}; border: 1px solid {BORDER};
    border-radius: 7px; padding: 8px 10px; selection-background-color: {ACCENT};
}}
QTextEdit:hover, QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{ border-color: #46485c; }}
QTextEdit:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border: 1px solid {ACCENT}; background: #1b1c29;
}}
QComboBox::drop-down {{ border: none; width: 28px; }}
QComboBox QAbstractItemView {{
    background: {SURFACE_RAISED}; color: {FG}; border: 1px solid {BORDER};
    selection-background-color: #392029; selection-color: {CREAM}; outline: none;
}}
QCheckBox {{ color: {FG}; spacing: 9px; }}
QCheckBox::indicator {{
    width: 17px; height: 17px; border: 1px solid #454759; border-radius: 5px; background: {SURFACE_RAISED};
}}
QCheckBox::indicator:checked {{
    border-color: {TEAL}; background: {TEAL};
}}
QSlider::groove:horizontal {{
    height: 5px; background: {BORDER}; border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {CREAM}; border: 3px solid {ACCENT}; width: 14px; margin: -7px 0; border-radius: 10px;
}}
QPushButton {{
    min-height: 20px; border-radius: 7px; padding: 9px 18px; font-weight: 600;
    background: {SURFACE_RAISED}; color: {FG}; border: 1px solid {BORDER};
}}
QPushButton:hover {{ background: #222432; border-color: #4a4c60; }}
QPushButton:pressed {{ background: #0d0e15; }}
QPushButton#primaryButton {{ background: {ACCENT}; color: white; border-color: {ACCENT}; min-width: 86px; }}
QPushButton#primaryButton:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QPushButton#secondaryButton {{ min-width: 74px; }}
QLabel#statusLabel {{ color: {TEAL}; }}
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #3b3d4d; border-radius: 4px; min-height: 28px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)

    def _load_values(self, cfg: dict, persona: str):
        self.persona_edit.setPlainText(persona or "")
        self.api_tab.load_values(cfg, self.original_brain)
        self.desktop_tab.load_values(cfg)
        self.vision_tab.load_values(cfg, self.original_brain)
        self.proactive_tab.load_values(cfg)
        self.tools_tab.load_values(self.original_brain)

    def _on_save(self):
        cfg = copy.deepcopy(self.original_config)
        brain = {}

        # Merge settings from all tabs
        self.api_tab.save_values(cfg, brain)
        self.desktop_tab.save_values(cfg)
        self.character_tab.save_values(cfg)
        self.vision_tab.save_values(cfg, brain)
        self.proactive_tab.save_values(cfg)
        self.tools_tab.save_values(brain)

        self.result_config = cfg
        self.result_brain = {key: value for key, value in brain.items() if self.original_brain.get(key) != value}
        self.result_persona = self.persona_edit.toPlainText().strip()
        self.accept()

    def results(self):
        """MilkChan settings, changed brain settings and the persona."""
        return self.result_config, self.result_brain, self.result_persona

    def done(self, result):
        if self.character_tab.is_busy():
            self.character_tab.status.setText('Finishing the import; please wait before closing settings.')
            return
        super().done(result)


class APITab(QWidget):
    """The brain's provider, key, model and thinking budget; MilkChan's update token."""

    def __init__(self, defaults: dict):
        super().__init__()
        self.defaults = defaults
        self._fetching = False
        self._models_loaded = False
        self._saved_chat_model = None
        self._model_fetch_worker = None
        self._build_ui()
        # Don't fetch models until after load_values() is called

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setFormAlignment(Qt.AlignLeft)
        form.setSpacing(10)

        # OpenAI API Key
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setPlaceholderText("sk-...")
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        form.addRow("Provider API key:", self.api_key_edit)

        # Base URL
        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText(f"{self.defaults['base_url']}  (SentientMilk default)")
        form.addRow("API base URL:", self.base_url_edit)

        # Chat Model with refresh button
        self.chat_model_combo = QComboBox()
        self.chat_model_combo.setEditable(True)
        self.chat_model_combo.setMinimumHeight(32)
        self.chat_model_combo.lineEdit().setPlaceholderText(f"{self.defaults['model']}  (SentientMilk default)")
        # Models will be populated from API on load
        chat_refresh_btn = QPushButton("🔄")
        chat_refresh_btn.setMinimumHeight(32)
        chat_refresh_btn.setMaximumWidth(40)
        chat_refresh_btn.setToolTip("Refresh models")
        chat_refresh_btn.clicked.connect(lambda: self._fetch_models_async())
        chat_layout = QHBoxLayout()
        chat_layout.addWidget(self.chat_model_combo)
        chat_layout.addWidget(chat_refresh_btn)
        chat_layout.setSpacing(5)
        chat_wrap = QWidget()
        chat_wrap.setLayout(chat_layout)
        form.addRow("Chat Model:", chat_wrap)

        from milkchan.desktop.services.brain import THINKING_MODES

        self.thinking_mode_combo = QComboBox()
        for label, value in THINKING_MODES:
            self.thinking_mode_combo.addItem(label, value)
        self.thinking_mode_combo.setToolTip(
            "More thinking can improve difficult answers but increases latency and cost. "
            "Available levels depend on your provider and model."
        )
        form.addRow("Thinking budget:", self.thinking_mode_combo)
        self.thinking_tokens_spin = QSpinBox()
        self.thinking_tokens_spin.setRange(1, 131072)
        self.thinking_tokens_spin.setSingleStep(1024)
        self.thinking_tokens_spin.setValue(4096)
        self.thinking_tokens_spin.setSuffix(" tokens")
        self.thinking_tokens_spin.setEnabled(False)
        self.thinking_tokens_spin.setToolTip(
            "Requires a provider supporting reasoning.max_tokens, such as OpenRouter. "
            "The model may enforce its own minimum and maximum."
        )
        self.thinking_mode_combo.currentIndexChanged.connect(
            lambda: self.thinking_tokens_spin.setEnabled(
                self.thinking_mode_combo.currentData() == "tokens"
            )
        )
        form.addRow("Custom token limit:", self.thinking_tokens_spin)

        # GitHub Token (for private framework repo updates)
        self.github_token_edit = QLineEdit()
        self.github_token_edit.setPlaceholderText("ghp_... (optional, for private repo updates)")
        self.github_token_edit.setEchoMode(QLineEdit.Password)
        form.addRow("GitHub Token:", self.github_token_edit)

        # Status label
        self.status_label = QLabel("")
        self.status_label.setObjectName("statusLabel")
        form.addRow("", self.status_label)

        layout.addLayout(form)
        layout.addStretch()

    def _fetch_models_async(self):
        """Fetch models in background thread"""
        if self._fetching:
            return
        self._fetching = True

        self.status_label.setText("Fetching models...")
        worker = ModelFetchWorker(self.api_key_edit.text().strip(), self.base_url_edit.text().strip(), self)
        worker.models_ready.connect(self._update_models)
        worker.finished.connect(self._model_fetch_finished)
        self._model_fetch_worker = worker
        worker.start()

    def _model_fetch_finished(self):
        self._fetching = False
        self._model_fetch_worker = None

    def _update_models(self, models: list):
        """Update combo boxes with fetched models"""
        # Save current text before clearing (in case user typed something)
        current_chat = self.chat_model_combo.currentText().strip()

        if not models:
            self.status_label.setText("No models from API - you can type manually")
            # Keep whatever user has typed
            return

        # Update chat model combo
        self.chat_model_combo.clear()
        for m in models:
            self.chat_model_combo.addItem(m)

        # RESTORE current text or saved values
        # Priority: current text > saved value > first model
        if current_chat:
            # User had typed something, preserve it
            if self.chat_model_combo.findText(current_chat) < 0:
                self.chat_model_combo.addItem(current_chat)
            self.chat_model_combo.setCurrentText(current_chat)
        elif hasattr(self, "_saved_chat_model") and self._saved_chat_model:
            index = self.chat_model_combo.findText(self._saved_chat_model)
            if index >= 0:
                self.chat_model_combo.setCurrentIndex(index)
            else:
                self.chat_model_combo.addItem(self._saved_chat_model)
                self.chat_model_combo.setCurrentText(self._saved_chat_model)

        self.status_label.setText(f"Loaded {len(models)} models from API")

    def load_values(self, cfg: dict, brain: dict):
        # The brain never reveals the key: the field only takes a new one.
        self.api_key_edit.setPlaceholderText(
            "Saved. Type a new key to replace it." if brain.get("api_key_set") else "sk-...")
        self.base_url_edit.setText(brain.get("base_url", ""))
        thinking_index = self.thinking_mode_combo.findData(brain.get("thinking_mode", "default"))
        self.thinking_mode_combo.setCurrentIndex(max(0, thinking_index))
        self.thinking_tokens_spin.setValue(brain.get("thinking_tokens", 4096))
        self.github_token_edit.setText(cfg.get("updates", {}).get("github_token", ""))

        self._saved_chat_model = brain.get("model", "")
        if self._saved_chat_model:
            self.chat_model_combo.setCurrentText(self._saved_chat_model)
        if brain.get("api_key_set"):
            self._fetch_models_async()

    def save_values(self, cfg: dict, brain: dict):
        brain.update(base_url=self.base_url_edit.text().strip(),
                     model=self.chat_model_combo.currentText().strip(),
                     thinking_mode=self.thinking_mode_combo.currentData(),
                     thinking_tokens=self.thinking_tokens_spin.value())
        if self.api_key_edit.text().strip():
            brain["api_key"] = self.api_key_edit.text().strip()
        cfg.setdefault("updates", {})["github_token"] = self.github_token_edit.text().strip()


class DesktopTab(QWidget):
    """Desktop Configuration Tab"""

    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setFormAlignment(Qt.AlignLeft)
        form.setSpacing(10)

        # Scale
        self.scale_slider = QSlider(Qt.Horizontal)
        self.scale_slider.setRange(50, 300)
        self.scale_spin = QSpinBox()
        self.scale_spin.setRange(50, 300)
        scale_layout = QHBoxLayout()
        scale_layout.addWidget(self.scale_slider, 1)
        scale_layout.addWidget(self.scale_spin)
        scale_wrap = QWidget()
        scale_wrap.setLayout(scale_layout)
        self.scale_slider.valueChanged.connect(self.scale_spin.setValue)
        self.scale_spin.valueChanged.connect(self.scale_slider.setValue)
        form.addRow("Scale (%)", scale_wrap)

        # Font size
        self.font_spin = QSpinBox()
        self.font_spin.setRange(6, 24)
        form.addRow("Font Size (px)", self.font_spin)

        # Char delay
        self.char_delay_spin = QSpinBox()
        self.char_delay_spin.setRange(10, 500)
        form.addRow("Char Delay (ms)", self.char_delay_spin)

        # Position
        self.x_spin = QSpinBox()
        self.x_spin.setRange(-2000, 2000)
        self.y_spin = QSpinBox()
        self.y_spin.setRange(-2000, 2000)
        pos_layout = QHBoxLayout()
        pos_layout.addWidget(QLabel("X:"))
        pos_layout.addWidget(self.x_spin)
        pos_layout.addWidget(QLabel("Y:"))
        pos_layout.addWidget(self.y_spin)
        pos_wrap = QWidget()
        pos_wrap.setLayout(pos_layout)
        form.addRow("Position Offset", pos_wrap)

        layout.addLayout(form)
        layout.addStretch()

    def load_values(self, cfg: dict):
        self.scale_slider.setValue(int(cfg.get("scale_factor", 100)))
        self.scale_spin.setValue(int(cfg.get("scale_factor", 100)))
        self.font_spin.setValue(int(cfg.get("font_size", 6)))
        self.char_delay_spin.setValue(int(cfg.get("char_delay_ms", 50)))

        pos = cfg.get("position", {})
        self.x_spin.setValue(int(pos.get("x_offset", 0)))
        self.y_spin.setValue(int(pos.get("y_offset", 0)))

    def save_values(self, cfg: dict):
        cfg["scale_factor"] = int(self.scale_spin.value())
        cfg["font_size"] = int(self.font_spin.value())
        cfg["char_delay_ms"] = int(self.char_delay_spin.value())
        cfg.setdefault("position", {})
        cfg["position"]["x_offset"] = int(self.x_spin.value())
        cfg["position"]["y_offset"] = int(self.y_spin.value())


class VisionTab(QWidget):
    """Vision Configuration Tab"""

    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setFormAlignment(Qt.AlignLeft)
        form.setSpacing(10)

        self.support_images_chk = QCheckBox("Send screenshots")
        self.support_images_chk.setToolTip("MilkChan attaches a screenshot of your screen to each message.")
        form.addRow("", self.support_images_chk)

        self.model_vision_chk = QCheckBox("The model accepts images")
        self.model_vision_chk.setToolTip(
            "Turn off for text-only models: the brain then keeps screenshots but does not send them."
        )
        form.addRow("", self.model_vision_chk)

        self.resize_spin = QDoubleSpinBox()
        self.resize_spin.setDecimals(2)
        self.resize_spin.setSingleStep(0.05)
        self.resize_spin.setRange(0.10, 1.00)
        self.resize_spin.setToolTip("Screenshots are captured at this fraction of the screen size.")
        form.addRow("Screenshot scale", self.resize_spin)

        self.request_budget_spin = QSpinBox()
        self.request_budget_spin.setRange(128, 16384)
        self.request_budget_spin.setSingleStep(128)
        self.request_budget_spin.setSuffix(" KiB")
        self.request_budget_spin.setToolTip(
            "Maximum prepared request size. 800 KiB fits behind nginx's common 1 MiB limit."
        )
        form.addRow("Request budget", self.request_budget_spin)

        layout.addLayout(form)
        layout.addStretch()

    def load_values(self, cfg: dict, brain: dict):
        proc = cfg.get("processing", {})
        self.support_images_chk.setChecked(bool(proc.get("support_images", True)))
        self.resize_spin.setValue(float(proc.get("screenshot_scale", 0.35)))
        self.model_vision_chk.setChecked(bool(brain.get("vision", True)))
        self.request_budget_spin.setValue(max(128, int(brain.get("request_budget", 800 * 1024)) // 1024))

    def save_values(self, cfg: dict, brain: dict):
        cfg.setdefault("processing", {})
        cfg["processing"]["support_images"] = self.support_images_chk.isChecked()
        cfg["processing"]["screenshot_scale"] = float(self.resize_spin.value())
        brain["vision"] = self.model_vision_chk.isChecked()
        brain["request_budget"] = int(self.request_budget_spin.value()) * 1024


class ProactiveTab(QWidget):
    """Proactive Monitoring Tab"""

    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setFormAlignment(Qt.AlignLeft)
        form.setSpacing(10)

        self.enabled_chk = QCheckBox("Speak up now and then without being asked")
        self.enabled_chk.setToolTip("Every 10 seconds to 2 minutes, with a fresh screenshot when images are on.")
        form.addRow("", self.enabled_chk)

        layout.addLayout(form)
        layout.addStretch()

    def load_values(self, cfg: dict):
        self.enabled_chk.setChecked(bool(cfg.get("proactive", {}).get("enabled", True)))

    def save_values(self, cfg: dict):
        cfg.setdefault("proactive", {})
        cfg["proactive"]["enabled"] = self.enabled_chk.isChecked()


class ToolsTab(QWidget):
    """Keys for the brain's tools; like the API key, they can be replaced but not read back."""

    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setFormAlignment(Qt.AlignLeft)
        form.setSpacing(10)

        # Web Search Token
        self.web_search_token_edit = QLineEdit()
        self.web_search_token_edit.setPlaceholderText("Enter web search API token...")
        self.web_search_token_edit.setEchoMode(QLineEdit.Password)
        form.addRow("Web Search Token:", self.web_search_token_edit)

        layout.addLayout(form)
        layout.addStretch()

    def load_values(self, brain: dict):
        if brain.get("web_search_key_set"):
            self.web_search_token_edit.setPlaceholderText("Saved. Type a new token to replace it.")

    def save_values(self, brain: dict):
        if self.web_search_token_edit.text().strip():
            brain["web_search_key"] = self.web_search_token_edit.text().strip()
