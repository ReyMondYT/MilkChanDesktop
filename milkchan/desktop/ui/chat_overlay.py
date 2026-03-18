import os
from PyQt5.QtCore import Qt, QTimer, QUrl, QSize
from PyQt5.QtGui import QFont, QFontDatabase, QTextCursor, QPixmap
from PyQt5.QtMultimedia import QMediaContent, QMediaPlayer
from PyQt5.QtWidgets import QWidget, QLabel, QTextEdit
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

        self.worker = None
        self.timer_reset_for_this_message = False
        self.last_emotion = None

        self.setup_ui()
        self.hide()

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

        self.ai_response = QTextEdit(self)
        self.ai_response.setReadOnly(True)
        self.ai_response.setStyleSheet('background-color: rgba(0,0,0,80); color: #5d2023; border: none; padding: 8px;')
        self.ai_response.installEventFilter(self)
        self.ai_response.hide()

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

        # Start narration loop, if configured
        if self.audio_player.mediaStatus() != QMediaPlayer.NoMedia:
            self.audio_player.stop()
            self.audio_player.play()

        self.response_timer.start(self.char_delay)

    def handle_error(self, error_message: str):
        print(f"Worker error: {error_message}")
        self.ai_response.clear()
        self.ai_response.setPlainText('Whoopsy! A background error occurred. Check the console for details.')
        self.parent().thinking = False
        self.parent().stop_speech_animation()
        self.audio_player.stop()

    def display_next_chunk(self):
        if self.displayed_chars >= len(self.current_response):
            self.response_timer.stop()
            self.audio_player.stop()
            self.parent().stop_speech_animation()
            return

        chunk_size = min(3, len(self.current_response) - self.displayed_chars)
        self.ai_response.insertPlainText(self.current_response[self.displayed_chars:self.displayed_chars + chunk_size])
        self.displayed_chars += chunk_size
        self.ai_response.moveCursor(QTextCursor.End)

        if self.audio_player.state() != QMediaPlayer.PlayingState:
            if self.displayed_chars < len(self.current_response):
                self.audio_player.play()

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