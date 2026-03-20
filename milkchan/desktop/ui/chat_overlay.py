import os
import json
import subprocess
import tempfile
import markdown2
from PyQt5.QtCore import Qt, QTimer, QUrl, QSize, pyqtSignal
from PyQt5.QtGui import QFont, QFontDatabase, QTextCursor, QPixmap
from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer
from PyQt5.QtWidgets import QWidget, QLabel, QTextEdit, QTextBrowser, QPushButton, QSizePolicy
from milkchan.desktop.services import ai_client
from milkchan.desktop.utils.sprites import load_sprite_mappings, build_sprite_tree_string
from milkchan.bootstrap import get_assets_dir

ASSETS_DIR = str(get_assets_dir())
FONT_PATH = os.path.join(ASSETS_DIR, 'Retro Gaming.ttf')
NARRATION_PATH = os.path.join(ASSETS_DIR, 'narr.mp3')
SPRITES_DIR = os.path.join(ASSETS_DIR, 'sprites')
OVERLAY_PATH = os.path.join(SPRITES_DIR, 'overlay.png')


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
    terminal_closed = pyqtSignal()

    def __init__(self, parent=None, config=None):
        super().__init__(parent)
        self.config = config or {}
        self.scale_factor = self.config.get('scale_factor', 100) / 100.0
        self.textbox_left, self.textbox_top = 5, 5
        self.textbox_width, self.textbox_height = 250, 70

        self.response_timer = QTimer(self)
        self.response_timer.timeout.connect(self.display_next_chunk)
        self.current_response = ''
        self.displayed_chars = 0
        self.char_delay = self.config.get('char_delay_ms', 50)

        self.audio_player = QMediaPlayer()
        if os.path.exists(NARRATION_PATH):
            url = QUrl.fromLocalFile(os.path.abspath(NARRATION_PATH))
            self.audio_player.setMedia(QMediaContent(url))
            # Loop audio while speaking
            self._audio_looper = QTimer(self)
            self._audio_looper.timeout.connect(self._loop_audio_if_speaking)
            self._audio_looper.start(100)

        self.worker = None
        self.timer_reset_for_this_message = False
        self.last_emotion = None

        self.chat_history = []
        self.terminal_process = None
        self.history_file = None

        self.setup_ui()
        self.hide()

    def _loop_audio_if_speaking(self):
        """Restart audio if we're still speaking and audio has stopped"""
        if self.parent() and hasattr(self.parent(), 'is_speaking'):
            if self.parent().is_speaking and self.audio_player.state() != QMediaPlayer.PlayingState:
                self.audio_player.play()

    def setup_ui(self):
        self.setStyleSheet('background-color: transparent;')

        self.bg_label = QLabel(self)
        if os.path.exists(OVERLAY_PATH):
            from PyQt5.QtGui import QPixmap as _QPixmap
            self.bg_pixmap = _QPixmap(OVERLAY_PATH)
            self.bg_label.setPixmap(self.bg_pixmap)

        font_id = QFontDatabase.addApplicationFont(FONT_PATH)
        self.font_family = QFontDatabase.applicationFontFamilies(font_id)[0] if font_id != -1 else 'Arial'
        # Base font size is treated as PIXELS for crispness and DPI independence
        self.base_font_size = int(self.config.get('font_size', 6)) if str(self.config.get('font_size', 6)).isdigit() else 6

        self.agent_question_label = QLabel(self)
        self.agent_question_label.setWordWrap(True)
        self.agent_question_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.agent_question_label.hide()

        self.user_input = ChatTextEdit(self)
        self.user_input.setStyleSheet('background-color: rgba(0,0,0,80); color: white; border: none; padding: 8px;')
        self.user_input.textChanged.connect(self.on_user_typing)

        self.ai_response = QTextBrowser(self)
        self.ai_response.setReadOnly(True)
        self.ai_response.setAcceptRichText(True)
        self.ai_response.setOpenExternalLinks(True)
        self.ai_response.setStyleSheet('background-color: rgba(0,0,0,80); color: #e6e6e6; border: none; padding: 8px;')
        self.ai_response.installEventFilter(self)
        self.ai_response.hide()

        self.expand_btn = QPushButton('[ ]', self)
        self.expand_btn.setFixedSize(24, 24)
        self.expand_btn.setCursor(Qt.PointingHandCursor)
        self.expand_btn.setStyleSheet('''
            QPushButton {
                background-color: rgba(172, 50, 50, 180);
                color: #e6e6e6;
                border: 2px solid #ac3232;
                border-radius: 4px;
                font-family: 'Retro Gaming', monospace;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #c23b3b;
                border-color: #c23b3b;
            }
        ''')
        self.expand_btn.setToolTip('Expand to terminal')
        self.expand_btn.hide()
        self.expand_btn.clicked.connect(self._open_terminal_chat)
        self.expand_btn.raise_()

        self._btn_hover_timer = QTimer(self)
        self._btn_hover_timer.setSingleShot(True)
        self._btn_hover_timer.timeout.connect(self._check_hover)

        # Initial sizing, fonts and placement
        self.update_scale(self.config.get('scale_factor', 100))
        self.update_textbox_position()

    def ask_agent_question(self, question: str):
        self.show()
        self.ai_response.hide()
        self.agent_question_label.show()
        self.user_input.show()
        self.user_input.clear()
        formatted = f'<p style="color: #FF4444;">{question}</p><p style="color: #44FF44;">Answer:</p>'
        self.agent_question_label.setText(formatted)
        self.user_input.setFocus()

    def hide_agent_question(self):
        self.agent_question_label.hide()
        self.user_input.clear()
        self.hide()
        self.parent().setAttribute(Qt.WA_TransparentForMouseEvents, True)

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
        if self.parent().is_answering_agent:
            return
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
        self._save_history_to_file()
        terminal_script = os.path.join(os.path.dirname(__file__), '..', '..', 'terminal_chat.py')
        terminal_script = os.path.abspath(terminal_script)

        # Stop any active response
        self.response_timer.stop()
        self.audio_player.stop()
        try:
            self.parent().stop_speech_animation()
        except Exception:
            pass

        # Hide all UI elements
        self.user_input.hide()
        self.ai_response.hide()
        self.agent_question_label.hide()
        self.expand_btn.hide()
        self.hide()

        if os.name == 'nt':
            self.terminal_process = subprocess.Popen([
                'cmd', '/c', 'start', 'cmd', '/k',
                'python', terminal_script, self.history_file
            ], shell=True)
        else:
            self.terminal_process = subprocess.Popen([
                'x-terminal-emulator', '-e', 'python', terminal_script, self.history_file
            ])

        self._start_terminal_watcher()

    def _save_history_to_file(self):
        if self.history_file is None:
            fd, self.history_file = tempfile.mkstemp(suffix='.json', prefix='milkchan_chat_')
            os.close(fd)
        with open(self.history_file, 'w', encoding='utf-8') as f:
            json.dump(self.chat_history, f)

    def _start_terminal_watcher(self):
        self._terminal_watcher = QTimer(self)
        self._terminal_watcher.timeout.connect(self._check_terminal_closed)
        self._terminal_watcher.start(500)

    def _check_terminal_closed(self):
        if self.terminal_process and self.terminal_process.poll() is not None:
            self._terminal_watcher.stop()
            self._load_history_from_file()
            self.terminal_process = None
            # Don't auto-show - let user decide when to open chatbox again

    def _load_history_from_file(self):
        if self.history_file and os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    self.chat_history = json.load(f)
            except Exception:
                pass

    def _add_to_history(self, role: str, content: str):
        self.chat_history.append({'role': role, 'content': content})

    def interrupt_response(self):
        self.response_timer.stop()
        self.audio_player.stop()
        self.parent().stop_speech_animation()
        self.switch_to_input_mode()

    def switch_to_input_mode(self):
        self.ai_response.hide()
        self.user_input.show()
        self.user_input.clear()
        self.user_input.setFocus()

    def position_overlay(self):
        if not self.parent():
            return
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
        self.agent_question_label.setGeometry(*geom)

        # Position expand button inside textbox area (top-right)
        btn_x = scaled_left + scaled_width - self.expand_btn.width() - 4
        btn_y = scaled_top + 4
        self.expand_btn.move(btn_x, btn_y)
        self.expand_btn.raise_()

    def update_scale(self, scale_percentage: int):
        # Scale the overlay art but keep text size constant in pixels (decoupled from sprite scale)
        self.scale_factor = max(0.5, min(3.0, scale_percentage / 100.0))

        if hasattr(self, 'bg_pixmap') and not self.bg_pixmap.isNull():
            current_sprite_width = int(260 * self.scale_factor)
            overlay_scale = current_sprite_width / self.bg_pixmap.width()
            scaled_size = QSize(int(self.bg_pixmap.width() * overlay_scale), int(self.bg_pixmap.height() * overlay_scale))
            self.bg_label.setPixmap(self.bg_pixmap.scaled(scaled_size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.bg_label.resize(scaled_size)
            self.setFixedSize(scaled_size)

        # Use pixel-size fonts for accuracy and crispness; do NOT multiply by scale factor
        font_size_px = max(int(self.base_font_size), 6)
        font = QFont(self.font_family)
        font.setPixelSize(font_size_px)
        self.user_input.setFont(font)
        self.ai_response.setFont(font)
        self.agent_question_label.setFont(font)

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
        if self.parent().is_answering_agent:
            self.parent().provide_answer_to_agent(text)
            self.hide_agent_question()
            return
        self._add_to_history('user', text)
        self.timer_reset_for_this_message = False
        self.user_input.hide()
        self.ai_response.clear()
        self.ai_response.show()
        self.ai_response.setFocus()
        self.ai_response.setPlainText('Thinking...')
        self.parent().thinking = True
        # Disconnect any previous worker's interim emotion to avoid stale updates
        try:
            if getattr(self, 'worker', None):
                try:
                    self.worker.emotion_ready.disconnect(self.handle_interim_emotion)
                except Exception:
                    pass
        except Exception:
            pass
        self.worker = self.parent().create_save_send_worker(text)
        # Reset last_emotion for this turn so new interim updates can apply
        try:
            self.last_emotion = None
        except Exception:
            pass
        self.worker.start()

    def handle_interim_emotion(self, emotion: dict):
        # Apply only valid emotions (pose, mood, variation); skip empty to avoid clobbering sprite state
        try:
            payload = emotion.get('emotion') if isinstance(emotion, dict) else None
            if isinstance(payload, list) and len(payload) >= 3:
                if getattr(self, 'last_emotion', None) != payload:
                    print(f"[ChatOverlay] Applying interim emotion: {payload}")
                    self.parent().update_sprite_emotion(payload)
                    self.last_emotion = payload
        except Exception as ex:
            print(f"[ChatOverlay] handle_interim_emotion error: {ex}")

    def handle_response(self, response: str, emotion: dict):
        if not self.isVisible():
            self.parent().setAttribute(Qt.WA_TransparentForMouseEvents, False)
            self.parent().chat_overlay.position_overlay()
            self.parent().chat_overlay.show()
            self.user_input.hide()
            self.ai_response.show()
            self.ai_response.setFocus()

        self.ai_response.clear()

        # Do not apply final emotion here to avoid double application.
        # Emotion updates are driven asynchronously (e.g., via emotion_ready/interim events).
        if emotion:
            self.handle_interim_emotion(emotion)

        # Now stop thinking and start rendering the text
        self.parent().thinking = False
        self.parent().start_speech_animation()

        self.current_response = response
        self.displayed_chars = 0
        self._add_to_history('assistant', response)

        # Start narration loop, if configured
        if self.audio_player.mediaStatus() != QMediaPlayer.NoMedia:
            self.audio_player.stop()
            self.audio_player.play()

        self.response_timer.start(self.char_delay)

    def handle_error(self, error: dict):
        error_type = error.get('type', 'unknown') if isinstance(error, dict) else 'unknown'
        error_message = error.get('message', 'An error occurred') if isinstance(error, dict) else str(error)
        error_details = error.get('details') if isinstance(error, dict) else None
        
        friendly_messages = {
            'rate_limit': "The AI service is busy right now. Please wait a moment and try again.",
            'timeout': "The request took too long. Please try again.",
            'network': "Could not connect to the AI service. Check your network connection.",
            'auth_error': "Authentication failed. Please check your API key configuration.",
            'payment_required': "API quota exceeded. Please add credits to your account.",
            'server_error': "The AI service is experiencing issues. Try again later.",
        }
        
        display_message = friendly_messages.get(error_type, error_message)
        
        print(f"[ChatOverlay] Error: {error_type} - {error_message}")
        self.ai_response.clear()
        
        error_html = f'''
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
            <div class="error-message">{display_message}</div>
            {f'<div class="error-details">{error_details}</div>' if error_details else ''}
        </div>
        '''
        self.ai_response.setHtml(error_html)
        
        self.parent().thinking = False
        self.parent().stop_speech_animation()
        self.audio_player.stop()

    def display_next_chunk(self):
        if self.displayed_chars >= len(self.current_response):
            self.response_timer.stop()
            self.audio_player.stop()
            self.parent().stop_speech_animation()
            self._render_markdown()
            return

        chunk_size = min(3, len(self.current_response) - self.displayed_chars)
        self.displayed_chars += chunk_size
        
        # Render markdown live during streaming
        self._render_markdown_streaming()

        if self.audio_player.state() != QMediaPlayer.PlayingState:
            if self.displayed_chars < len(self.current_response):
                self.audio_player.play()

    def _close_unclosed_tags(self, text: str) -> str:
        import re
        open_tags = []
        tag_pattern = re.compile(r'<(/?\w+)[^>]*>')
        for match in tag_pattern.finditer(text):
            tag = match.group(1)
            if tag.startswith('/'):
                tag_name = tag[1:]
                if open_tags and open_tags[-1] == tag_name:
                    open_tags.pop()
            else:
                open_tags.append(tag)
        for tag in reversed(open_tags):
            text += f'</{tag}>'
        return text

    def _render_markdown_streaming(self):
        text_so_far = self.current_response[:self.displayed_chars]
        
        try:
            html = markdown2.markdown(
                text_so_far,
                extras=['fenced-code-blocks', 'code-friendly', 'tables', 'strike', 'task_list']
            )
            html = self._close_unclosed_tags(html)
        except Exception:
            html = text_so_far.replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br>')
        
        styled_html = f'''
        <style>
            body {{ color: #e6e6e6; font-family: '{self.font_family}', sans-serif; }}
            h1, h2, h3, h4, h5, h6 {{ color: #ff6b6b; margin-top: 12px; margin-bottom: 6px; }}
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
                border-left: 3px solid #ac3232;
                margin: 8px 0;
                padding-left: 12px;
                color: #9a9a9a;
            }}
            ul, ol {{ margin: 6px 0; padding-left: 20px; }}
            li {{ margin: 2px 0; }}
            a {{ color: #8be9fd; text-decoration: none; }}
            strong {{ color: #ffb86c; }}
            em {{ color: #f1fa8c; }}
            hr {{ border: none; border-top: 1px solid #3a3a4e; margin: 12px 0; }}
        </style>
        {html}
        '''
        self.ai_response.setHtml(styled_html)
        self._scroll_to_bottom()

    def _scroll_to_bottom(self):
        scrollbar = self.ai_response.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _render_markdown(self):
        html = markdown2.markdown(
            self.current_response,
            extras=['fenced-code-blocks', 'code-friendly', 'tables', 'strike', 'task_list']
        )
        styled_html = f'''
        <style>
            body {{ color: #e6e6e6; font-family: '{self.font_family}', sans-serif; }}
            h1, h2, h3, h4, h5, h6 {{ color: #ff6b6b; margin-top: 12px; margin-bottom: 6px; }}
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
                border-left: 3px solid #ac3232;
                margin: 8px 0;
                padding-left: 12px;
                color: #9a9a9a;
            }}
            ul, ol {{ margin: 6px 0; padding-left: 20px; }}
            li {{ margin: 2px 0; }}
            a {{ color: #8be9fd; text-decoration: none; }}
            strong {{ color: #ffb86c; }}
            em {{ color: #f1fa8c; }}
            hr {{ border: none; border-top: 1px solid #3a3a4e; margin: 12px 0; }}
        </style>
        {html}
        '''
        self.ai_response.setHtml(styled_html)
        self._scroll_to_bottom()

    def hide_overlay(self):
        self.response_timer.stop()
        self.audio_player.stop()
        self.parent().stop_speech_animation()

        if self.worker and self.worker.isRunning():
            try:
                self.worker.response_ready.disconnect()
                self.worker.error.disconnect()
                # Also disconnect interim emotion to avoid stray signals
                self.worker.emotion_ready.disconnect()
            except Exception:
                pass

        proactive_worker = self.parent().proactive_worker
        if proactive_worker and proactive_worker.isRunning():
            try:
                proactive_worker.response_ready.disconnect()
                proactive_worker.error.disconnect()
            except Exception:
                pass
            self.parent().schedule_proactive_message()

        self.agent_question_label.hide()
        self.hide()