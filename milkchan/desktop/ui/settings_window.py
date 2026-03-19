"""
MilkChan Settings Window - Tabbed Interface

Organized into logical sections:
- API Config: OpenAI keys, models, base URLs
- Desktop: Scale, font, position, delays
- Vision: Capture mode, resize factor
- Proactive: Monitoring settings
"""

import os
import copy
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QFontDatabase
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton,
    QSpinBox, QDoubleSpinBox, QTextEdit, QSlider, QWidget, QComboBox,
    QCheckBox, QDesktopWidget, QTabWidget, QGroupBox, QLineEdit
)
from milkchan.bootstrap import get_assets_dir

ASSETS_DIR = str(get_assets_dir())
FONT_PATH = os.path.join(ASSETS_DIR, 'Retro Gaming.ttf')

ACCENT = '#ac3232'
BG = '#0d0d14'
FG = '#e6e6e6'
MUTED = '#9a9a9a'


def load_retro_font() -> str:
    family = 'Arial'
    try:
        fid = QFontDatabase.addApplicationFont(FONT_PATH)
        fams = QFontDatabase.applicationFontFamilies(fid)
        if fams:
            family = fams[0]
    except Exception:
        pass
    return family


class SettingsWindow(QDialog):
    def __init__(self, parent: QWidget, config: dict, persona: str):
        super().__init__(parent)
        self.setWindowTitle('Milk Chan Settings')
        self.setModal(True)
        self.setMinimumWidth(650)
        self.setMinimumHeight(500)

        self.original_config = copy.deepcopy(config)
        self.original_persona = persona or ''
        self.result_config = None
        self.result_persona = None

        self.font_family = load_retro_font()
        base_px = max(int(self.original_config.get('font_size', 6)), 6)
        base_font = QFont(self.font_family)
        base_font.setPixelSize(base_px)
        self.setFont(base_font)

        self._build_ui()
        self._load_values(config, persona)
        self._apply_style()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Title
        title = QLabel('⚙️ Milk Chan Settings')
        title.setObjectName('title')
        title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(title)

        # Tab widget
        self.tabs = QTabWidget()
        self.tabs.setObjectName('settingsTabs')
        layout.addWidget(self.tabs)

        # Create tab pages
        self.api_tab = APITab(self.original_config)
        self.desktop_tab = DesktopTab(self.original_config)
        self.vision_tab = VisionTab(self.original_config)
        self.proactive_tab = ProactiveTab(self.original_config)
        self.tools_tab = ToolsTab(self.original_config)

        # Add tabs
        self.tabs.addTab(self.api_tab, '🔑 API Config')
        self.tabs.addTab(self.tools_tab, '🔧 Tools')
        self.tabs.addTab(self.desktop_tab, '🖥️ Desktop')
        self.tabs.addTab(self.vision_tab, '👁️ Vision')
        self.tabs.addTab(self.proactive_tab, '⚡ Proactive')

        # Persona section (always visible)
        persona_group = QGroupBox('Persona')
        persona_layout = QVBoxLayout()
        self.persona_edit = QTextEdit()
        self.persona_edit.setPlaceholderText('Describe Milk Chan\'s personality and behavior...')
        self.persona_edit.setFixedHeight(100)
        persona_layout.addWidget(self.persona_edit)
        persona_group.setLayout(persona_layout)
        layout.addWidget(persona_group)

        # Buttons
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_btn = QPushButton('Cancel')
        self.save_btn = QPushButton('Save')
        buttons.addWidget(self.cancel_btn)
        buttons.addWidget(self.save_btn)
        layout.addLayout(buttons)

        self.cancel_btn.clicked.connect(self.reject)
        self.save_btn.clicked.connect(self._on_save)

    def _apply_style(self):
        self.setStyleSheet(f"""
QDialog {{
    background-color: {BG};
    color: {FG};
    border: 2px solid {ACCENT};
    border-radius: 8px;
}}
QLabel#title {{
    color: {ACCENT};
    font-size: 20px;
    font-weight: bold;
    padding-bottom: 8px;
}}
QTabWidget::pane {{
    border: 2px solid {ACCENT};
    border-radius: 6px;
    background-color: {BG};
}}
QTabBar::tab {{
    background-color: #1a1a2e;
    color: {FG};
    border: 2px solid #2a2a3e;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 8px 16px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background-color: {BG};
    border-color: {ACCENT};
    color: {ACCENT};
}}
QTabBar::tab:hover:!selected {{
    background-color: #2a2a3e;
}}
QLabel {{
    color: #e6e6e6;
}}
QFormLayout QLabel {{
    color: #e6e6e6;
    font-weight: bold;
}}
QGroupBox {{
    font-weight: bold;
    margin-top: 12px;
    padding-top: 10px;
    border: 2px solid {ACCENT};
    border-radius: 6px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 5px;
    color: {ACCENT};
}}
QFormLayout QLabel {{
    color: {FG};
    font-weight: bold;
}}
QTextEdit, QLineEdit {{
    background-color: #141420;
    color: {FG};
    border: 2px solid #26263a;
    border-radius: 6px;
    padding: 8px;
    selection-background-color: {ACCENT};
    selection-color: {BG};
}}
QSpinBox, QDoubleSpinBox, QComboBox {{
    background-color: #141420;
    color: {FG};
    border: 2px solid #26263a;
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: {ACCENT};
    selection-color: {BG};
}}
QCheckBox {{
    color: {FG};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border: 2px solid #26263a;
    border-radius: 4px;
    background: #141420;
}}
QCheckBox::indicator:checked {{
    border-color: {ACCENT};
    background: {ACCENT};
}}
QSlider::groove:horizontal {{
    height: 8px;
    background: #26263a;
    border-radius: 4px;
}}
QSlider::handle:horizontal {{
    background: {ACCENT};
    border: 2px solid {ACCENT};
    width: 20px;
    margin: -6px 0;
    border-radius: 10px;
}}
QPushButton {{
    background-color: {ACCENT};
    color: {BG};
    border: 2px solid {ACCENT};
    border-radius: 6px;
    padding: 10px 20px;
    font-weight: bold;
}}
QPushButton:hover {{
    background-color: #c23b3b;
    border-color: #c23b3b;
}}
QPushButton:pressed {{
    background-color: #a32f2f;
}}
        """)

        # Apply font to widgets
        base_px = max(int(self.original_config.get('font_size', 6)), 6)
        f = QFont(self.font_family)
        f.setPixelSize(base_px)
        for w in [self.persona_edit, self.cancel_btn, self.save_btn]:
            w.setFont(f)

    def _load_values(self, cfg: dict, persona: str):
        self.persona_edit.setPlainText(persona or '')
        self.api_tab.load_values(cfg)
        self.desktop_tab.load_values(cfg)
        self.vision_tab.load_values(cfg)
        self.proactive_tab.load_values(cfg)
        self.tools_tab.load_values(cfg)

    def _on_save(self):
        cfg = copy.deepcopy(self.original_config)

        # Merge settings from all tabs
        self.api_tab.save_values(cfg)
        self.desktop_tab.save_values(cfg)
        self.vision_tab.save_values(cfg)
        self.proactive_tab.save_values(cfg)
        self.tools_tab.save_values(cfg)

        self.result_config = cfg
        self.result_persona = self.persona_edit.toPlainText().strip()
        self.accept()

    def results(self):
        return self.result_config, self.result_persona


class APITab(QWidget):
    """API Configuration Tab"""
    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self._fetching = False
        self._models_loaded = False
        self._saved_chat_model = None
        self._saved_vision_model = None
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
        self.api_key_edit.setPlaceholderText('sk-...')
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        form.addRow('OpenAI API Key:', self.api_key_edit)

        # Base URL
        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText('https://api.openai.com/v1')
        form.addRow('Base URL:', self.base_url_edit)

        # Chat Model with refresh button
        self.chat_model_combo = QComboBox()
        self.chat_model_combo.setEditable(True)
        self.chat_model_combo.setMinimumHeight(32)
        # Models will be populated from API on load
        chat_refresh_btn = QPushButton('🔄')
        chat_refresh_btn.setMinimumHeight(32)
        chat_refresh_btn.setMaximumWidth(40)
        chat_refresh_btn.setToolTip('Refresh models')
        chat_refresh_btn.clicked.connect(lambda: self._fetch_models_async())
        chat_layout = QHBoxLayout()
        chat_layout.addWidget(self.chat_model_combo)
        chat_layout.addWidget(chat_refresh_btn)
        chat_layout.setSpacing(5)
        chat_wrap = QWidget()
        chat_wrap.setLayout(chat_layout)
        form.addRow('Chat Model:', chat_wrap)

        # Vision Model
        self.vision_model_combo = QComboBox()
        self.vision_model_combo.setEditable(True)
        self.vision_model_combo.setMinimumHeight(32)
        # Models will be populated from API on load
        vision_refresh_btn = QPushButton('🔄')
        vision_refresh_btn.setMinimumHeight(32)
        vision_refresh_btn.setMaximumWidth(40)
        vision_refresh_btn.setToolTip('Refresh models')
        vision_refresh_btn.clicked.connect(lambda: self._fetch_models_async())
        vision_layout = QHBoxLayout()
        vision_layout.addWidget(self.vision_model_combo)
        vision_layout.addWidget(vision_refresh_btn)
        vision_layout.setSpacing(5)
        vision_wrap = QWidget()
        vision_wrap.setLayout(vision_layout)
        form.addRow('Vision Model:', vision_wrap)
        
        # GitHub Token (for private framework repo updates)
        self.github_token_edit = QLineEdit()
        self.github_token_edit.setPlaceholderText('ghp_... (optional, for private repo updates)')
        self.github_token_edit.setEchoMode(QLineEdit.Password)
        form.addRow('GitHub Token:', self.github_token_edit)

        # Status label
        self.status_label = QLabel('')
        self.status_label.setObjectName('statusLabel')
        form.addRow('', self.status_label)

        layout.addLayout(form)
        layout.addStretch()

    def _fetch_models_async(self):
        """Fetch models in background thread"""
        if self._fetching:
            return
        self._fetching = True
        
        import threading
        
        def fetch_thread():
            try:
                api_key = self.api_key_edit.text().strip()
                base_url = self.base_url_edit.text().strip()
                
                from milkchan.desktop.services.model_fetcher import get_available_models
                models = get_available_models(api_key if api_key else None, base_url if base_url else None)
                
                # Store result
                self._pending_models = models
                
                # Use timer to update in main thread
                from PyQt5.QtCore import QTimer
                QTimer.singleShot(0, self._do_update_models)
                
            except Exception as e:
                print(f"Error fetching models: {e}")
                self._pending_models = []
                from PyQt5.QtCore import QTimer
                QTimer.singleShot(0, self._do_update_models)
            finally:
                self._fetching = False
        
        self.status_label.setText('Fetching models...')
        threading.Thread(target=fetch_thread, daemon=True).start()
    
    def _do_update_models(self):
        """Actually update models in main thread"""
        models = getattr(self, '_pending_models', [])
        self._update_models(models)
    
    def _update_models(self, models: list):
        """Update combo boxes with fetched models"""
        # Save current text before clearing (in case user typed something)
        current_chat = self.chat_model_combo.currentText().strip()
        current_vision = self.vision_model_combo.currentText().strip()
        
        if not models:
            self.status_label.setText('No models from API - you can type manually')
            # Keep whatever user has typed
            return

        # Update chat model combo
        self.chat_model_combo.clear()
        for m in models:
            self.chat_model_combo.addItem(m)

        # Update vision model combo
        self.vision_model_combo.clear()
        for m in models:
            # Add all models to vision - user can choose any
            self.vision_model_combo.addItem(m)

        # RESTORE current text or saved values
        # Priority: current text > saved value > first model
        if current_chat:
            # User had typed something, preserve it
            if self.chat_model_combo.findText(current_chat) < 0:
                self.chat_model_combo.addItem(current_chat)
            self.chat_model_combo.setCurrentText(current_chat)
        elif hasattr(self, '_saved_chat_model') and self._saved_chat_model:
            index = self.chat_model_combo.findText(self._saved_chat_model)
            if index >= 0:
                self.chat_model_combo.setCurrentIndex(index)
            else:
                self.chat_model_combo.addItem(self._saved_chat_model)
                self.chat_model_combo.setCurrentText(self._saved_chat_model)

        if current_vision:
            # User had typed something, preserve it
            if self.vision_model_combo.findText(current_vision) < 0:
                self.vision_model_combo.addItem(current_vision)
            self.vision_model_combo.setCurrentText(current_vision)
        elif hasattr(self, '_saved_vision_model') and self._saved_vision_model:
            index = self.vision_model_combo.findText(self._saved_vision_model)
            if index >= 0:
                self.vision_model_combo.setCurrentIndex(index)
            else:
                self.vision_model_combo.addItem(self._saved_vision_model)
                self.vision_model_combo.setCurrentText(self._saved_vision_model)

        self.status_label.setText(f'Loaded {len(models)} models from API')

    def load_values(self, cfg: dict):
        self.api_key_edit.setText(cfg.get('openai_api_key', ''))
        self.base_url_edit.setText(cfg.get('openai_base_url', ''))
        
        # Load GitHub token from updates config
        updates_cfg = cfg.get('updates', {})
        self.github_token_edit.setText(updates_cfg.get('github_token', ''))

        # Store saved values BEFORE doing anything else
        self._saved_chat_model = cfg.get('openai_chat_model', '')
        self._saved_vision_model = cfg.get('openai_vision_model', '')

        # Set current selections from saved config
        if self._saved_chat_model:
            self.chat_model_combo.setCurrentText(self._saved_chat_model)
        if self._saved_vision_model:
            self.vision_model_combo.setCurrentText(self._saved_vision_model)

        # Fetch models after loading saved values
        if cfg.get('openai_api_key'):
            self._fetch_models_async()

    def save_values(self, cfg: dict):
        # Only save non-empty values to avoid overwriting existing config
        api_key = self.api_key_edit.text().strip()
        base_url = self.base_url_edit.text().strip()
        chat_model = self.chat_model_combo.currentText().strip()
        vision_model = self.vision_model_combo.currentText().strip()
        github_token = self.github_token_edit.text().strip()
        
        if api_key:
            cfg['openai_api_key'] = api_key
        if base_url:
            cfg['openai_base_url'] = base_url
        if chat_model:
            cfg['openai_chat_model'] = chat_model
        if vision_model:
            cfg['openai_vision_model'] = vision_model
        
        # Save GitHub token to updates config
        if 'updates' not in cfg:
            cfg['updates'] = {}
        if github_token:
            cfg['updates']['github_token'] = github_token


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
        form.addRow('Scale (%)', scale_wrap)

        # Font size
        self.font_spin = QSpinBox()
        self.font_spin.setRange(6, 24)
        form.addRow('Font Size (px)', self.font_spin)

        # Char delay
        self.char_delay_spin = QSpinBox()
        self.char_delay_spin.setRange(10, 500)
        form.addRow('Char Delay (ms)', self.char_delay_spin)

        # Sprite Resolution Scale
        self.sprite_res_combo = QComboBox()
        self.sprite_res_combo.addItem('Low (0.5x) - ~70MB', 0.5)
        self.sprite_res_combo.addItem('Medium (1.0x) - ~280MB', 1.0)
        self.sprite_res_combo.addItem('High (1.5x) - ~630MB', 1.5)
        self.sprite_res_combo.addItem('Ultra (2.0x) - ~1.1GB', 2.0)
        form.addRow('Sprite Quality', self.sprite_res_combo)

        # Position
        self.x_spin = QSpinBox()
        self.x_spin.setRange(-2000, 2000)
        self.y_spin = QSpinBox()
        self.y_spin.setRange(-2000, 2000)
        pos_layout = QHBoxLayout()
        pos_layout.addWidget(QLabel('X:'))
        pos_layout.addWidget(self.x_spin)
        pos_layout.addWidget(QLabel('Y:'))
        pos_layout.addWidget(self.y_spin)
        pos_wrap = QWidget()
        pos_wrap.setLayout(pos_layout)
        form.addRow('Position Offset', pos_wrap)

        layout.addLayout(form)
        layout.addStretch()

    def load_values(self, cfg: dict):
        self.scale_slider.setValue(int(cfg.get('scale_factor', 100)))
        self.scale_spin.setValue(int(cfg.get('scale_factor', 100)))
        self.font_spin.setValue(int(cfg.get('font_size', 6)))
        self.char_delay_spin.setValue(int(cfg.get('char_delay_ms', 50)))
        
        # Sprite resolution scale
        sprite_scale = float(cfg.get('sprite_resolution_scale', 1.0))
        for i in range(self.sprite_res_combo.count()):
            if abs(self.sprite_res_combo.itemData(i) - sprite_scale) < 0.01:
                self.sprite_res_combo.setCurrentIndex(i)
                break
        
        pos = cfg.get('position', {})
        self.x_spin.setValue(int(pos.get('x_offset', 0)))
        self.y_spin.setValue(int(pos.get('y_offset', 0)))

    def save_values(self, cfg: dict):
        cfg['scale_factor'] = int(self.scale_spin.value())
        cfg['font_size'] = int(self.font_spin.value())
        cfg['char_delay_ms'] = int(self.char_delay_spin.value())
        cfg['sprite_resolution_scale'] = float(self.sprite_res_combo.currentData() or 1.0)
        cfg.setdefault('position', {})
        cfg['position']['x_offset'] = int(self.x_spin.value())
        cfg['position']['y_offset'] = int(self.y_spin.value())


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

        # Capture mode
        self.capture_mode_combo = QComboBox()
        self.capture_mode_combo.addItem('Video (video + audio)', 'video')
        self.capture_mode_combo.addItem('Image (screenshots only)', 'image')
        form.addRow('Capture Mode', self.capture_mode_combo)

        # Resize factor
        self.resize_spin = QDoubleSpinBox()
        self.resize_spin.setDecimals(2)
        self.resize_spin.setSingleStep(0.05)
        self.resize_spin.setRange(0.25, 1.00)
        form.addRow('Resize Factor', self.resize_spin)

        # Screenshot on disabled
        self.sshot_chk = QCheckBox('Take one screenshot when vision is disabled')
        form.addRow('', self.sshot_chk)

        layout.addLayout(form)
        layout.addStretch()

    def load_values(self, cfg: dict):
        proc = cfg.get('processing', {})
        mode = proc.get('vision_mode', 'video')
        
        for i in range(self.capture_mode_combo.count()):
            if self.capture_mode_combo.itemData(i) == mode:
                self.capture_mode_combo.setCurrentIndex(i)
                break
        
        self.resize_spin.setValue(float(proc.get('video_resize_factor', 0.5)))
        self.sshot_chk.setChecked(bool(proc.get('screenshot_on_disabled_vision', True)))

    def save_values(self, cfg: dict):
        cfg.setdefault('processing', {})
        mode = self.capture_mode_combo.currentData() or 'video'
        cfg['processing']['vision_mode'] = mode
        cfg['processing']['vision_enabled'] = mode == 'video'
        cfg['processing']['audio_enabled'] = mode == 'video'
        cfg['processing']['video_resize_factor'] = float(self.resize_spin.value())
        cfg['processing']['screenshot_on_disabled_vision'] = self.sshot_chk.isChecked()


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

        # Enabled
        self.enabled_chk = QCheckBox('Enable proactive monitoring')
        form.addRow('', self.enabled_chk)

        # Sample interval
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(100, 10000)
        self.interval_spin.setSingleStep(100)
        form.addRow('Sample Interval (ms)', self.interval_spin)

        # Change threshold
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setDecimals(2)
        self.threshold_spin.setSingleStep(0.01)
        self.threshold_spin.setRange(0.01, 1.0)
        form.addRow('Change Threshold', self.threshold_spin)

        # Min interval
        self.min_interval_spin = QDoubleSpinBox()
        self.min_interval_spin.setRange(1.0, 120.0)
        self.min_interval_spin.setSingleStep(1.0)
        form.addRow('Min Interval (sec)', self.min_interval_spin)

        layout.addLayout(form)
        layout.addStretch()

    def load_values(self, cfg: dict):
        proactive = cfg.get('proactive', {})
        self.enabled_chk.setChecked(bool(proactive.get('enabled', True)))
        self.interval_spin.setValue(int(proactive.get('sample_interval_ms', 1200)))
        self.threshold_spin.setValue(float(proactive.get('change_threshold', 0.08)))
        self.min_interval_spin.setValue(float(proactive.get('min_interval_sec', 15.0)))

    def save_values(self, cfg: dict):
        cfg.setdefault('proactive', {})
        cfg['proactive']['enabled'] = self.enabled_chk.isChecked()
        cfg['proactive']['sample_interval_ms'] = int(self.interval_spin.value())
        cfg['proactive']['change_threshold'] = float(self.threshold_spin.value())
        cfg['proactive']['min_interval_sec'] = float(self.min_interval_spin.value())


class ToolsTab(QWidget):
    """SentientMilk Tools Configuration Tab"""
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

        # Web Search Token
        self.web_search_token_edit = QLineEdit()
        self.web_search_token_edit.setPlaceholderText('Enter web search API token...')
        self.web_search_token_edit.setEchoMode(QLineEdit.Password)
        form.addRow('Web Search Token:', self.web_search_token_edit)

        layout.addLayout(form)
        layout.addStretch()

    def load_values(self, cfg: dict):
        tools = cfg.get('tools', {})
        self.web_search_token_edit.setText(tools.get('web_search_token', ''))

    def save_values(self, cfg: dict):
        web_search_token = self.web_search_token_edit.text().strip()
        cfg.setdefault('tools', {})
        if web_search_token:
            cfg['tools']['web_search_token'] = web_search_token
