"""The chat box drawn over the character: input, typed-out replies and errors."""

import html
import re
import shutil
import subprocess
import sys
from pathlib import Path

import markdown2
from PyQt5.QtCore import QSize, Qt, QTimer
from PyQt5.QtGui import QFont, QFontDatabase, QPixmap
from PyQt5.QtWidgets import QLabel, QPushButton, QTextBrowser, QTextEdit, QWidget

from milkchan.core.config import get_config
from milkchan.desktop.agents.agent_workers import ChatWorker
from milkchan.desktop.utils.audio_player import NarrationPlayer
from milkchan.paths import get_assets_dir
from milkchan.runtime_env import external_process_environment

ASSETS_DIR = get_assets_dir()
FONT_PATH = str(ASSETS_DIR / 'Retro Gaming.ttf')
NARRATION_PATH = str(ASSETS_DIR / 'narr.mp3')
OVERLAY_PATH = str(ASSETS_DIR / 'overlay.png')
TERMINAL_SCRIPT = Path(__file__).resolve().parents[2] / 'terminal_chat.py'
MARKDOWN_EXTRAS = ['fenced-code-blocks', 'code-friendly', 'tables', 'strike', 'task_list']

CHAT_SURFACE = 'rgba(10, 11, 17, 218)'
CHAT_BORDER = 'rgba(196, 71, 77, 205)'
CHAT_TEXT = '#f0dfbd'
CHAT_MUTED = '#9a9baa'

FRIENDLY_ERRORS = {
    'rate_limit': "The AI service is busy right now. Please wait a moment and try again.",
    'timeout': "The request took too long. Please try again.",
    'network': "Could not connect to the AI service. Check your network connection.",
    'auth_error': "Authentication failed. Please check your API key configuration.",
    'config_missing': "No API key yet. Open Settings → Connection and enter it.",
    'payment_required': "API quota exceeded. Please add credits to your account.",
    'server_error': "The AI service is experiencing issues. Try again later.",
    'payload_too_large': "This conversation is too large for the API gateway. "
                         "Your history is still saved; increase the server request limit or clear history.",
    'brain_unreachable': "Can't reach SentientMilk, MilkChan's brain. Restart MilkChan to bring it back.",
}


class ChatTextEdit(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptRichText(False)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if not (event.modifiers() & Qt.ShiftModifier):
                self.parent().submit_text()
                return
        elif event.key() == Qt.Key_Escape:
            self.parent().hide_overlay()
            return
        super().keyPressEvent(event)


class ChatOverlay(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.config = get_config()
        self.scale_factor = self.config.get('scale_factor', 100) / 100.0
        self.textbox_left, self.textbox_top = 5, 5
        self.textbox_width, self.textbox_height = 250, 70

        self.response_timer = QTimer(self)
        self.response_timer.timeout.connect(self.display_next_chunk)
        self.current_response = ''
        self.displayed_chars = 0
        self.char_delay = self.config.get('char_delay_ms', 50)

        self.audio_player = NarrationPlayer(NARRATION_PATH)
        self._audio_looper = QTimer(self)
        self._audio_looper.timeout.connect(self._loop_audio_if_speaking)
        self._audio_looper.start(100)

        self.worker = None
        self.timer_reset_for_this_message = False

        self.setup_ui()
        self.hide()

    def _loop_audio_if_speaking(self):
        if self.parent().is_speaking:
            self.audio_player.ensure_playing()

    def setup_ui(self):
        self.setStyleSheet('background-color: transparent;')

        self.bg_label = QLabel(self)
        self.bg_pixmap = QPixmap(OVERLAY_PATH)
        self.bg_label.setPixmap(self.bg_pixmap)

        font_id = QFontDatabase.addApplicationFont(FONT_PATH)
        self.font_family = QFontDatabase.applicationFontFamilies(font_id)[0] if font_id != -1 else 'Arial'
        # Pixels, for crisp text at any DPI.
        self.base_font_size = int(self.config.get('font_size', 6))

        self.user_input = ChatTextEdit(self)
        self.user_input.setStyleSheet(f'''
            QTextEdit {{
                background: {CHAT_SURFACE}; color: {CHAT_TEXT};
                border: 1px solid {CHAT_BORDER}; border-radius: 9px;
                padding: 9px 35px 9px 11px; selection-background-color: #c4474d;
            }}
            QTextEdit:focus {{ border: 1px solid #db5960; background: rgba(15, 16, 24, 232); }}
            QScrollBar:vertical {{ background: transparent; width: 7px; }}
            QScrollBar::handle:vertical {{ background: #4a3440; border-radius: 3px; min-height: 20px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        ''')
        self.user_input.textChanged.connect(self.on_user_typing)

        self.ai_response = QTextBrowser(self)
        self.ai_response.setReadOnly(True)
        self.ai_response.setAcceptRichText(True)
        self.ai_response.setOpenExternalLinks(True)
        self.ai_response.setStyleSheet(f'''
            QTextBrowser {{
                background: {CHAT_SURFACE}; color: {CHAT_TEXT};
                border: 1px solid rgba(40, 185, 177, 165); border-radius: 9px;
                padding: 9px 35px 9px 11px;
            }}
            QScrollBar:vertical {{ background: transparent; width: 7px; }}
            QScrollBar::handle:vertical {{ background: #275651; border-radius: 3px; min-height: 20px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        ''')
        self.ai_response.installEventFilter(self)
        self.ai_response.hide()

        self.expand_btn = QPushButton('↗', self)
        self.expand_btn.setFixedSize(24, 24)
        self.expand_btn.setCursor(Qt.PointingHandCursor)
        self.expand_btn.setStyleSheet('''
            QPushButton {
                background-color: rgba(23, 25, 37, 225);
                color: #f0dfbd;
                border: 1px solid rgba(196, 71, 77, 210);
                border-radius: 7px;
                font-family: 'Retro Gaming', monospace;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #c4474d;
                border-color: #db5960;
            }
        ''')
        self.expand_btn.setToolTip('Open extended chat')
        self.expand_btn.hide()
        self.expand_btn.clicked.connect(self._open_terminal_chat)
        self.expand_btn.raise_()

        self._btn_hover_timer = QTimer(self)
        self._btn_hover_timer.setSingleShot(True)
        self._btn_hover_timer.timeout.connect(self._check_hover)

        self.apply_config()

    def apply_config(self):
        """Pick up settings and the active character."""
        self.base_font_size = int(self.config.get('font_size', 6))
        self.char_delay = self.config.get('char_delay_ms', 50)
        self.user_input.setPlaceholderText(
            f'Talk to {self.parent().character.name}…    Enter to send  ·  Shift+Enter for a new line'
        )
        self.update_scale(self.config.get('scale_factor', 100))

    def eventFilter(self, obj, event):
        if obj is self.ai_response and event.type() == event.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
                if self.response_timer.isActive():
                    self.interrupt_response()
                else:
                    self.switch_to_input_mode()
                return True
        return super().eventFilter(obj, event)

    def on_user_typing(self):
        is_empty = not self.user_input.toPlainText()
        if not is_empty and not self.timer_reset_for_this_message:
            self.parent().schedule_proactive_message()
            self.timer_reset_for_this_message = True
        elif is_empty and self.timer_reset_for_this_message:
            self.timer_reset_for_this_message = False

    def enterEvent(self, event):
        self.expand_btn.show()
        self._btn_hover_timer.start(100)

    def leaveEvent(self, event):
        self._btn_hover_timer.stop()
        if not self.expand_btn.underMouse():
            self.expand_btn.hide()

    def _check_hover(self):
        if not self.underMouse() and not self.expand_btn.underMouse():
            self.expand_btn.hide()
        else:
            self._btn_hover_timer.start(100)

    def _open_terminal_chat(self):
        self.response_timer.stop()
        self.parent().stop_speech_animation()
        self.user_input.hide()
        self.ai_response.hide()
        self.expand_btn.hide()
        self.hide()

        if getattr(sys, 'frozen', False):
            command = [sys.executable, '--terminal-chat']
        else:
            command = [sys.executable, str(TERMINAL_SCRIPT)]
        env = external_process_environment()
        env['MILKCHAN_IPC_TOKEN'] = self.parent().ipc_server.token
        if sys.platform == 'win32':
            subprocess.Popen(['cmd', '/c', 'start', '', 'cmd', '/k', *command], env=env)
        else:
            terminal = shutil.which('x-terminal-emulator') or 'x-terminal-emulator'
            subprocess.Popen([terminal, '-e', *command], env=env, close_fds=True)

    def interrupt_response(self):
        self.response_timer.stop()
        self.parent().stop_speech_animation()
        self.switch_to_input_mode()

    def switch_to_input_mode(self):
        self.ai_response.hide()
        self.user_input.show()
        self.user_input.clear()
        self.user_input.setFocus()

    def position_overlay(self):
        x = max(0, (self.parent().width() - self.width()) // 2)
        y = max(0, self.parent().height() - self.height())
        self.move(x, y)

    def update_textbox_position(self):
        scaled_left = int(self.textbox_left * self.scale_factor)
        scaled_top = int(self.textbox_top * self.scale_factor)
        scaled_width = min(int(self.textbox_width * self.scale_factor), self.width() - scaled_left - 5)
        scaled_height = min(int(self.textbox_height * self.scale_factor), self.height() - scaled_top - 5)
        geom = (scaled_left, scaled_top, scaled_width, scaled_height)
        self.user_input.setGeometry(*geom)
        self.ai_response.setGeometry(*geom)
        self.expand_btn.move(scaled_left + scaled_width - self.expand_btn.width() - 4, scaled_top + 4)
        self.expand_btn.raise_()

    def update_scale(self, scale_percentage: int):
        # The overlay art scales with the character; text keeps its pixel size.
        self.scale_factor = max(0.5, min(3.0, scale_percentage / 100.0))
        if not self.bg_pixmap.isNull():
            overlay_scale = int(260 * self.scale_factor) / self.bg_pixmap.width()
            scaled_size = QSize(int(self.bg_pixmap.width() * overlay_scale),
                                int(self.bg_pixmap.height() * overlay_scale))
            self.bg_label.setPixmap(self.bg_pixmap.scaled(scaled_size, Qt.KeepAspectRatio,
                                                          Qt.SmoothTransformation))
            self.bg_label.resize(scaled_size)
            self.setFixedSize(scaled_size)
        font = QFont(self.font_family)
        font.setPixelSize(max(int(self.base_font_size), 6))
        self.user_input.setFont(font)
        self.ai_response.setFont(font)
        self.update_textbox_position()
        if self.isVisible():
            self.position_overlay()

    def show_overlay(self):
        self.show()
        self.switch_to_input_mode()

    def submit_text(self):
        text = self.user_input.toPlainText().strip()
        if not text:
            return
        self.parent().ipc_server.notify_tui_new_message('user', text)
        self.timer_reset_for_this_message = False
        self.user_input.hide()
        self.ai_response.clear()
        self.ai_response.show()
        self.ai_response.setFocus()
        self.ai_response.setPlainText('Thinking...')
        self.parent().set_thinking(True)
        self.worker = ChatWorker(text, self)
        self.worker.response_ready.connect(self.handle_response)
        self.worker.error.connect(self.handle_error)
        self.worker.finished.connect(self._forget_worker)
        self.worker.start()

    def _forget_worker(self):
        if self.sender() is self.worker:
            self.worker = None

    def handle_response(self, response: str, sprite):
        if not self.isVisible():
            self.parent().setAttribute(Qt.WA_TransparentForMouseEvents, False)
            self.position_overlay()
            self.show()
            self.user_input.hide()
            self.ai_response.show()
            self.ai_response.setFocus()
        self.ai_response.clear()
        if sprite:
            self.parent().set_expression(sprite['pose'], sprite['mood'])
        self.parent().set_thinking(False)
        self.parent().start_speech_animation()
        self.current_response = response
        self.displayed_chars = 0
        self.parent().ipc_server.notify_tui_new_message('assistant', response, sprite)
        self.response_timer.start(self.char_delay)

    def handle_error(self, error: dict):
        error_type = error.get('type', 'unknown')
        message = html.escape(FRIENDLY_ERRORS.get(error_type, error.get('message') or 'An error occurred'))
        details = html.escape(error['details']) if error.get('details') else ''
        self.ai_response.setHtml(f'''
        <style>
            body {{ color: #e6e6e6; font-family: '{self.font_family}', sans-serif; }}
            .error-container {{
                background-color: rgba(172, 50, 50, 0.3);
                border-left: 3px solid #ac3232;
                padding: 12px;
                margin: 8px 0;
                border-radius: 4px;
            }}
            .error-title {{ color: #ff6b6b; font-weight: bold; margin-bottom: 8px; }}
            .error-message {{ color: #e6e6e6; }}
            .error-details {{ color: #9a9a9a; font-size: 0.9em; margin-top: 8px; }}
        </style>
        <div class="error-container">
            <div class="error-title">Error</div>
            <div class="error-message">{message}</div>
            {f'<div class="error-details">{details}</div>' if details else ''}
        </div>
        ''')
        self.parent().set_thinking(False)
        self.parent().stop_speech_animation()

    def display_next_chunk(self):
        if self.displayed_chars >= len(self.current_response):
            self.response_timer.stop()
            self.parent().stop_speech_animation()
            self._render_markdown(self.current_response)
            return
        self.displayed_chars += min(3, len(self.current_response) - self.displayed_chars)
        self._render_markdown(self.current_response[:self.displayed_chars], partial=True)

    @staticmethod
    def _close_unclosed_tags(text: str) -> str:
        open_tags = []
        for match in re.finditer(r'<(/?\w+)[^>]*>', text):
            tag = match.group(1)
            if not tag.startswith('/'):
                open_tags.append(tag)
            elif open_tags and open_tags[-1] == tag[1:]:
                open_tags.pop()
        return text + ''.join(f'</{tag}>' for tag in reversed(open_tags))

    def _render_markdown(self, text: str, partial: bool = False):
        # Raw HTML in a reply is shown as text, never rendered.
        body = markdown2.markdown(text, extras=MARKDOWN_EXTRAS, safe_mode='escape')
        if partial:
            body = self._close_unclosed_tags(body)
        self.ai_response.setHtml(f'''
        <style>
            body {{ color: {CHAT_TEXT}; font-family: '{self.font_family}', sans-serif; }}
            h1, h2, h3, h4, h5, h6 {{ color: #db5960; margin-top: 12px; margin-bottom: 6px; }}
            h1 {{ font-size: 1.4em; }}
            h2 {{ font-size: 1.2em; }}
            h3 {{ font-size: 1.1em; }}
            p {{ margin: 6px 0; }}
            code {{
                background-color: #2a2a3e;
                color: #ff79c6;
                padding: 2px 6px;
                border-radius: 4px;
                font-family: '{self.font_family}', sans-serif !important;
            }}
            pre {{
                background-color: #1a1a2e;
                border: 1px solid #3a3a4e;
                border-radius: 6px;
                padding: 10px;
                overflow-x: auto;
                margin: 8px 0;
            }}
            pre code {{
                background-color: transparent;
                color: #f8f8f2;
                padding: 0;
            }}
            blockquote {{
                border-left: 3px solid #c4474d;
                margin: 8px 0;
                padding-left: 12px;
                color: {CHAT_MUTED};
            }}
            ul, ol {{ margin: 6px 0; padding-left: 20px; }}
            li {{ margin: 2px 0; }}
            a {{ color: #28b9b1; text-decoration: none; }}
            strong {{ color: #f0dfbd; }}
            em {{ color: #f1fa8c; }}
            hr {{ border: none; border-top: 1px solid #3a3a4e; margin: 12px 0; }}
        </style>
        {body}
        ''')
        scrollbar = self.ai_response.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def hide_overlay(self):
        self.response_timer.stop()
        self.parent().stop_speech_animation()
        if self.worker:
            # The reply is still saved to history; it is just not shown.
            self.worker.response_ready.disconnect(self.handle_response)
            self.worker.error.disconnect(self.handle_error)
            self.worker = None
            self.parent().set_thinking(False)
        self.hide()
