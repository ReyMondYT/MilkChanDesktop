"""Chat turns run off the UI thread."""

import logging
import traceback
from typing import Optional

from PyQt5.QtCore import QThread, pyqtSignal

from milkchan.core.config import get_config
from milkchan.desktop.services import brain
from milkchan.desktop.utils.screenshot import take_screenshot

logger = logging.getLogger(__name__)


def send_message(message: Optional[str], event: Optional[dict] = None) -> brain.ChatResult:
    """One turn with a fresh screenshot. Without a message: an event (a reminder, a finished task),
    or an idle turn in which the brain may stay silent."""
    config = get_config()
    screenshot = take_screenshot(config.get('processing.screenshot_scale')) \
        if config.get('processing.support_images') else None
    try:
        return brain.turn(message, screenshot, config.get('username'), event)
    finally:
        if screenshot:
            screenshot.unlink(missing_ok=True)


class ChatWorker(QThread):
    response_ready = pyqtSignal(str, object)  # reply, {'pose', 'mood'} or None
    error = pyqtSignal(dict)

    def __init__(self, text: Optional[str], parent=None, event: Optional[dict] = None):
        super().__init__(parent)
        self.text, self.event = text, event
        self.finished.connect(self.deleteLater)

    def run(self):
        try:
            result = send_message(self.text, self.event)
        except Exception as exc:
            logger.exception('Chat worker failed')
            self.error.emit(brain.create_error('worker_error', str(exc), traceback.format_exc()))
            return
        if result['error']:
            self.error.emit(result['error'])
        else:
            self.response_ready.emit(result['response'], result['sprite'])
