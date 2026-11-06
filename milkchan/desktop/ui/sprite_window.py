"""The desktop character: draws and animates the sprite and hosts the chat overlay."""

import logging
import random
import sys
import time

from PyQt5.QtCore import (
    QAbstractNativeEventFilter,
    QCoreApplication,
    Qt,
    QThread,
    QTimer,
    pyqtSignal,
    pyqtSlot,
)
from PyQt5.QtWidgets import QApplication, QLabel, QMainWindow, QMenu, QMessageBox

from milkchan.core.config import get_config
from milkchan.core.updater import format_update_message, get_updater, updates_supported
from milkchan.desktop.agents.agent_workers import ChatWorker
from milkchan.desktop.services import brain
from milkchan.desktop.services.ipc_server import get_ipc_server
from milkchan.desktop.sprites.character import DEFAULT_MOOD
from milkchan.desktop.sprites.library import active_character
from milkchan.desktop.sprites.renderer import BASE_HEIGHT, SpriteRenderer
from milkchan.desktop.ui.chat_overlay import ChatOverlay
from milkchan.desktop.ui.settings_window import SettingsWindow

logger = logging.getLogger(__name__)

BLINK_MS = 150

if sys.platform.startswith('win'):
    from ctypes import wintypes

    WM_HOTKEY = 0x0312
    MOD_NOREPEAT = 0x4000
    VK_F8 = 0x77
    HOTKEY_ID_F8 = 1

    class _WinHotkeyFilter(QAbstractNativeEventFilter):
        """F8 toggles the character even while it is hidden."""

        def __init__(self, on_f8_callback):
            super().__init__()
            self._on_f8 = on_f8_callback

        def nativeEventFilter(self, eventType, message):
            if eventType in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID_F8:
                    self._on_f8()
                    return True, 0
            return False, 0


class _Task(QThread):
    """Run a blocking call off the UI thread and deliver its result."""

    done = pyqtSignal(object)

    def __init__(self, function, parent):
        super().__init__(parent)
        self._function = function
        self.finished.connect(self.deleteLater)

    def run(self):
        self.done.emit(self._function())


class SpriteWindow(QMainWindow):
    toggle_visibility_signal = pyqtSignal()
    notification_signal = pyqtSignal(dict)  # from the brain's notification thread

    def __init__(self):
        super().__init__()
        self.config = get_config()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        # Clicks pass through the character until the chat overlay is open.
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.label = QLabel(self)
        self.setCentralWidget(self.label)

        self.character = None
        self.renderer = None
        self.pose = None
        self.mood = DEFAULT_MOOD
        self.variant = 1
        self.is_speaking = False
        self.mouth_open = False
        self.is_blinking = False
        self.thinking = False
        self._last_toggle_ts = 0.0

        self.mouth_timer = QTimer(self)
        self.mouth_timer.timeout.connect(self.animate_mouth)
        self.blink_timer = QTimer(self)
        self.blink_timer.setSingleShot(True)
        self.blink_timer.timeout.connect(self.start_blink)
        self.blink_end_timer = QTimer(self)
        self.blink_end_timer.setSingleShot(True)
        self.blink_end_timer.timeout.connect(self.end_blink)
        self.proactive_message_timer = QTimer(self)
        self.proactive_message_timer.setSingleShot(True)
        self.proactive_message_timer.timeout.connect(self.send_proactive_message)

        self._load_character()
        self.chat_overlay = ChatOverlay(self)
        self.toggle_visibility_signal.connect(self.toggle_visibility)
        self._register_hotkey()
        self.update_position()
        self.schedule_next_blink()
        self.schedule_proactive_message()

        self.ipc_server = get_ipc_server()
        self.ipc_server.set_sprite_window(self)
        self.ipc_server.start()
        QApplication.instance().aboutToQuit.connect(self.ipc_server.stop)
        self._notification_workers = []
        self.notification_signal.connect(self.tell_about)
        brain.listen(self.notification_signal.emit, self.config.get('brain.events_cursor', -1),
                     lambda cursor: self.config.set('brain.events_cursor', cursor))

    def _register_hotkey(self):
        self._hotkey_filter = None
        if not sys.platform.startswith('win'):
            return
        import ctypes

        if ctypes.windll.user32.RegisterHotKey(int(self.winId()), HOTKEY_ID_F8, MOD_NOREPEAT, VK_F8):
            self._hotkey_filter = _WinHotkeyFilter(self.toggle_visibility_signal.emit)
            QCoreApplication.instance().installNativeEventFilter(self._hotkey_filter)
        else:
            logger.warning("Failed to register the global F8 hotkey")

    # ============== Sprite ==============

    def _load_character(self):
        self.character = active_character()
        height = max(1, round(BASE_HEIGHT * int(self.config.get('scale_factor', 100)) / 100))
        self.renderer = SpriteRenderer(self.character, height)
        self.setFixedSize(self.renderer.size)
        moods = self.character.moods()
        pose = self.pose if self.pose in moods else next(iter(moods))
        self.pose = None  # the new renderer has nothing retained yet
        self.set_expression(pose, self.mood)
        try:
            brain.declare(self.character)
        except brain.BrainError as exc:
            logger.error("Could not tell the brain about %s: %s", self.character.name, exc)

    @pyqtSlot(str, str)
    def set_expression(self, pose: str, mood: str):
        """Show a pose and mood; unknown names keep the pose and fall back to neutral."""
        moods = self.character.moods()
        if pose not in moods:
            pose = self.pose or next(iter(moods))
        if mood not in moods[pose]:
            mood = DEFAULT_MOOD
        if (pose, mood) != (self.pose, self.mood):
            self.pose, self.mood, self.variant = pose, mood, 1
            self.renderer.retain(pose, mood)
        self.update_sprite()

    def update_sprite(self):
        eyes = 'eyes_closed' if self.is_blinking else 'eyes_half' if self.thinking else None
        mouth = ('mouth_full' if self.mouth_open else 'mouth_half') if self.is_speaking else None
        self.label.setPixmap(self.renderer.render(self.pose, self.mood, self.variant, eyes, mouth))

    def set_thinking(self, thinking: bool):
        self.thinking = thinking
        self.update_sprite()

    def animate_mouth(self):
        self.mouth_open = not self.mouth_open
        self.update_sprite()

    @pyqtSlot()
    def start_speech_animation(self):
        was_speaking = self.is_speaking
        self.is_speaking = True
        self.mouth_timer.start(max(100, int(self.chat_overlay.char_delay * 2)))
        player = self.chat_overlay.audio_player
        if player.is_available():
            if was_speaking:
                player.ensure_playing()
            else:
                player.stop()
                player.play()
        self.update_sprite()

    @pyqtSlot()
    def stop_speech_animation(self):
        self.mouth_timer.stop()
        self.is_speaking = False
        self.mouth_open = False
        self.chat_overlay.audio_player.stop()
        self.update_sprite()

    def start_blink(self):
        self.is_blinking = True
        self.update_sprite()
        self.blink_end_timer.start(BLINK_MS)

    def end_blink(self):
        self.is_blinking = False
        # Idle variants such as glances appear between blinks.
        self.variant = random.randint(1, self.character.variant_count(self.pose, self.mood))
        self.update_sprite()
        self.schedule_next_blink()

    def schedule_next_blink(self):
        self.blink_timer.start(random.randint(2000, 8000))

    # ============== Proactive messages ==============

    def schedule_proactive_message(self):
        self.proactive_message_timer.stop()
        if self.config.get('proactive.enabled', True) and brain.is_configured():
            self.proactive_message_timer.start(random.randint(10_000, 120_000))

    def send_proactive_message(self):
        if self.chat_overlay.user_input.isActiveWindow() or self.ipc_server.is_tui_active():
            self.schedule_proactive_message()  # the user is typing here or in the terminal
            return
        self.set_thinking(True)
        self.proactive_worker = ChatWorker(None, self)
        self.proactive_worker.response_ready.connect(self.handle_proactive_response)
        self.proactive_worker.error.connect(self.chat_overlay.handle_error)
        self.proactive_worker.start()

    def handle_proactive_response(self, response: str, sprite):
        if response:
            self.chat_overlay.handle_response(response, sprite)
        else:  # the brain had nothing to say
            self.set_thinking(False)
            if sprite:
                self.set_expression(sprite['pose'], sprite['mood'])
        self.schedule_proactive_message()

    @pyqtSlot(dict)
    def tell_about(self, notification: dict):
        """A reminder came due or a background task ended: MilkChan says so in its own words."""
        self.set_thinking(True)
        worker = ChatWorker(None, self, event=brain.event_for(notification))
        worker.response_ready.connect(self.chat_overlay.handle_response)
        worker.error.connect(self.chat_overlay.handle_error)
        self._notification_workers = [w for w in self._notification_workers if w.isRunning()] + [worker]
        worker.start()

    # ============== Window ==============

    def toggle_visibility(self):
        now = time.time()
        if now - self._last_toggle_ts < 0.2:
            return  # one key press can arrive twice
        self._last_toggle_ts = now
        if self.isVisible():
            self.hide()
            self.blink_timer.stop()
            self.proactive_message_timer.stop()
            self.stop_speech_animation()
            self.chat_overlay.hide()
        else:
            self.show()
            self.schedule_next_blink()
            self.schedule_proactive_message()

    def update_position(self):
        screen = QApplication.primaryScreen().geometry()
        x_off = max(-screen.width(), min(screen.width(), int(self.config.get('position.x_offset', 0))))
        y_off = max(-screen.height(), min(screen.height(), int(self.config.get('position.y_offset', 0))))
        self.move(screen.width() - self.width() + x_off, screen.height() - self.height() + y_off)

    def contextMenuEvent(self, event):
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        menu = QMenu(self)
        menu.addAction('Settings', self.open_settings)
        menu.addAction('Check for Updates', self.check_for_updates)
        menu.addAction('Clear History', self.clear_history)
        menu.addAction('Exit', QApplication.quit)
        menu.exec_(self.mapToGlobal(event.pos()))
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def open_settings(self):
        try:
            persona = brain.persona()
            brain_settings = {'config': brain.client().config(), 'persona': persona}
        except brain.BrainError as exc:
            QMessageBox.warning(self, 'Settings', f"Can't reach SentientMilk, MilkChan's brain: {exc.message}")
            return
        old_look = (self.config.get('character'), self.config.get('scale_factor'))
        dialog = SettingsWindow(self, self.config.as_dict(), brain_settings)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        accepted = dialog.exec_() == dialog.Accepted
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        if not accepted:
            return
        new_config, brain_changes, new_persona = dialog.results()
        self.config.update(new_config)
        try:
            if brain_changes:
                brain.client().update_config(**brain_changes)
            if new_persona != persona:
                brain.set_persona(new_persona)
        except brain.BrainError as exc:
            QMessageBox.warning(self, 'Settings', f"SentientMilk kept its previous settings: {exc.message}")
        if (self.config.get('character'), self.config.get('scale_factor')) != old_look:
            self._load_character()
        self.chat_overlay.apply_config()
        self.update_position()
        self.schedule_proactive_message()

    def clear_history(self):
        try:
            brain.clear_history()
        except brain.BrainError as exc:
            self.chat_overlay.handle_error(exc.as_dict())
            return
        self.ipc_server.notify_tui_clear_history()
        self.set_expression(self.pose, 'smile')
        self.chat_overlay.handle_response('History cleared!', None)

    def _run_task(self, function, on_done):
        task = _Task(function, self)
        task.done.connect(on_done)
        task.start()

    def check_for_updates(self):
        if not updates_supported():
            QMessageBox.information(self, 'Updates', 'This is a development checkout. '
                                    'Update MilkChan and SentientMilk with git.')
            return
        self.chat_overlay.handle_response('Checking for updates...', None)
        self._run_task(get_updater().check_for_updates, self._on_update_checked)

    def _on_update_checked(self, info):
        if info is None:
            QMessageBox.warning(self, 'Update Check Failed', 'Could not reach GitHub. Check your internet '
                                'connection, and the GitHub token in settings for a private repository.')
        elif not info.available:
            self.chat_overlay.handle_response('You are up to date!', None)
        elif QMessageBox.question(
            self, 'Update Available',
            format_update_message(info) + '\n\nApply this update now? MilkChan will restart.',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        ) == QMessageBox.Yes:
            self.chat_overlay.handle_response('Applying update...', None)
            self._run_task(get_updater().apply_update, self._on_update_applied)
        else:
            self.chat_overlay.handle_response('Update postponed.', None)

    def _on_update_applied(self, applied: bool):
        if not applied:
            QMessageBox.critical(self, 'Update Failed', 'Failed to apply update.\n\nPlease check the logs for details.')
            return
        QMessageBox.information(self, 'Update Applied', 'Update applied successfully!\n\nMilkChan will now restart.')
        from milkchan.process import restart_app

        restart_app()
        QApplication.quit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_F7:
            if self.chat_overlay.isVisible():
                self.chat_overlay.hide_overlay()
                self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            else:
                self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
                self.chat_overlay.position_overlay()
                self.chat_overlay.show_overlay()
        elif event.key() == Qt.Key_F8 and not sys.platform.startswith('win'):
            self.toggle_visibility()  # on Windows the global hotkey handles F8
        else:
            super().keyPressEvent(event)
