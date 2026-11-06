"""Local IPC for the terminal chat: one JSON command per connection.

The server and its event stream listen on 127.0.0.1 only and require the token
MilkChan hands to the terminal it launches (``MILKCHAN_IPC_TOKEN``), so other
local programs cannot chat as the user or read the history.
"""

import hmac
import json
import logging
import secrets
import socket
import threading
from typing import Any, Dict, Optional

from milkchan.desktop.services.stream_broker import (
    MAX_REQUEST_BYTES,
    EventType,
    StreamEventBroker,
    read_line,
)

logger = logging.getLogger(__name__)

DEFAULT_PORT = 19527
STREAM_PORT = 19528
TOKEN_ENV = 'MILKCHAN_IPC_TOKEN'

_TOOL_EVENTS = {'tool_start': EventType.TOOL_START, 'tool_end': EventType.TOOL_END,
                'tool_error': EventType.TOOL_ERROR}
# Commands that only drive the sprite window: name -> its slot.
_WINDOW_SLOTS = {'start_speech': 'start_speech_animation', 'stop_speech': 'stop_speech_animation'}


class IPCServer:
    def __init__(self, port: int = DEFAULT_PORT, stream_port: int = STREAM_PORT):
        self.port = port
        self.stream_port = stream_port
        self.token = secrets.token_urlsafe(32)
        self.sprite_window = None
        self.running = False
        self.server_socket: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._tui_active = False
        self._broker = StreamEventBroker(self.token, port=stream_port)

    def set_sprite_window(self, sprite_window):
        self.sprite_window = sprite_window

    def _on_tool_event(self, event: Dict[str, Any]):
        self._broker.publish(_TOOL_EVENTS.get(event.get('type'), EventType.TOOL_END), event)

    def start(self):
        if self.running:
            return
        from milkchan.desktop.services import brain

        brain.set_tool_event_callback(self._on_tool_event)
        self.running = True
        self._thread = threading.Thread(target=self._run_server, daemon=True)
        self._thread.start()
        self._broker.start()

    def stop(self):
        self.running = False
        self._broker.stop()
        if self.server_socket:
            try:
                self.server_socket.close()
            except OSError:
                pass
        if self._thread:
            self._thread.join(timeout=1)

    def _run_server(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(('127.0.0.1', self.port))
        self.server_socket.listen(5)
        self.server_socket.settimeout(1.0)
        while self.running:
            try:
                conn, _ = self.server_socket.accept()
            except socket.timeout:
                continue
            except OSError as exc:
                if self.running:
                    logger.error("IPC server error: %s", exc)
                continue
            threading.Thread(target=self._handle_client, args=(conn,), daemon=True).start()

    def _handle_client(self, conn: socket.socket):
        try:
            conn.settimeout(30.0)
            message = json.loads(read_line(conn, MAX_REQUEST_BYTES).decode('utf-8'))
            if not isinstance(message, dict):
                raise ValueError('request must be a JSON object')
            conn.settimeout(None)  # a chat turn may take minutes
            response = self.process_message(message)
        except (OSError, ValueError) as exc:
            response = {'error': str(exc)}
        try:
            conn.sendall((json.dumps(response) + '\n').encode('utf-8'))
        except OSError as exc:
            logger.debug("IPC client went away: %s", exc)
        finally:
            conn.close()

    def process_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        if not hmac.compare_digest(str(message.get('token', '')), self.token):
            return {'error': 'unauthorized'}
        command = message.get('command', '')
        params = message.get('params') or {}
        if command == 'ping':
            return {'status': 'ok', 'message': 'pong'}
        if command == 'tui_start':
            self._tui_active = True
            name = self.sprite_window.character.name if self.sprite_window else None
            return {'status': 'ok', 'stream_port': self.stream_port, 'name': name}
        if command == 'tui_end':
            self._tui_active = False
            return {'status': 'ok'}
        if command == 'chat':
            return self._handle_chat(str(params.get('message', '')))
        if command == 'get_history':
            from milkchan.desktop.services import brain

            try:
                return {'status': 'ok', 'history': brain.history()}
            except brain.BrainError as exc:
                return {'status': 'error', 'error': exc.as_dict()}
        if command == 'set_sprite':
            sprite = params.get('sprite') or {}
            self._invoke('set_expression', str(sprite.get('pose', '')), str(sprite.get('mood', '')))
            return {'status': 'ok'}
        if command in _WINDOW_SLOTS:
            self._invoke(_WINDOW_SLOTS[command])
            return {'status': 'ok'}
        return {'error': f'Unknown command: {command}'}

    @staticmethod
    def _handle_chat(user_message: str) -> Dict[str, Any]:
        from milkchan.desktop.agents.agent_workers import send_message

        try:
            result = send_message(user_message)
        except Exception as exc:
            logger.exception("[IPC] chat failed")
            return {'status': 'error', 'error': {'type': 'ipc_error', 'message': str(exc), 'details': None}}
        if result['error']:
            return {'status': 'error', 'error': result['error']}
        return {'status': 'ok', 'response': result['response'], 'sprite': result['sprite'],
                'tools': result['tools']}

    def _invoke(self, slot: str, *args: str):
        """Call a sprite window slot on the Qt main thread."""
        if not self.sprite_window:
            return
        from PyQt5.QtCore import Q_ARG, QMetaObject, Qt

        QMetaObject.invokeMethod(self.sprite_window, slot, Qt.QueuedConnection,
                                 *(Q_ARG(str, arg) for arg in args))

    def notify_tui_clear_history(self):
        if self._tui_active:
            self._broker.publish(EventType.CHAT_RESPONSE, {'type': 'system', 'action': 'clear_history'})

    def notify_tui_new_message(self, role: str, content: str, sprite: Optional[dict] = None):
        """Show a message from the chat box in the terminal too."""
        if self._tui_active:
            self._broker.publish(EventType.CHAT_RESPONSE, {'type': 'sync_message', 'role': role,
                                                           'content': content, 'sprite': sprite})

    def is_tui_active(self) -> bool:
        return self._tui_active


_ipc_server: Optional[IPCServer] = None


def get_ipc_server() -> IPCServer:
    global _ipc_server
    if _ipc_server is None:
        _ipc_server = IPCServer()
    return _ipc_server
