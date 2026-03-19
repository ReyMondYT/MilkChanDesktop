"""
IPC Server for MilkChan

Provides a local socket server for external processes (like terminal_chat)
to communicate with the main MilkChan application.
"""

import json
import socket
import threading
import logging
from typing import Callable, Dict, Any, Optional

logger = logging.getLogger(__name__)

DEFAULT_PORT = 19527


class IPCServer:
    def __init__(self, port: int = DEFAULT_PORT):
        self.port = port
        self.server_socket: Optional[socket.socket] = None
        self.running = False
        self.handlers: Dict[str, Callable] = {}
        self._thread: Optional[threading.Thread] = None
        self.sprite_window = None

    def register_handler(self, command: str, handler: Callable):
        self.handlers[command] = handler

    def set_sprite_window(self, sprite_window):
        self.sprite_window = sprite_window

    def start(self):
        if self.running:
            return

        self.running = True
        self._thread = threading.Thread(target=self._run_server, daemon=True)
        self._thread.start()
        logger.info(f"IPC server started on port {self.port}")

    def stop(self):
        self.running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=1)
        logger.info("IPC server stopped")

    def _run_server(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind(('127.0.0.1', self.port))
        self.server_socket.listen(5)
        self.server_socket.settimeout(1.0)

        while self.running:
            try:
                conn, addr = self.server_socket.accept()
                thread = threading.Thread(target=self._handle_client, args=(conn,), daemon=True)
                thread.start()
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    logger.error(f"IPC server error: {e}")

    def _handle_client(self, conn: socket.socket):
        try:
            conn.settimeout(30.0)
            data = b''
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
                if b'\n' in data:
                    break

            if data:
                message = json.loads(data.decode('utf-8').strip())
                response = self._process_message(message)
                conn.sendall((json.dumps(response) + '\n').encode('utf-8'))
        except Exception as e:
            logger.error(f"Client handler error: {e}")
            try:
                conn.sendall((json.dumps({'error': str(e)}) + '\n').encode('utf-8'))
            except Exception:
                pass
        finally:
            conn.close()

    def _process_message(self, message: Dict[str, Any]) -> Dict[str, Any]:
        command = message.get('command', '')
        params = message.get('params', {})

        if command == 'ping':
            return {'status': 'ok', 'message': 'pong'}

        if command == 'shutdown':
            return {'status': 'ok', 'message': 'shutting_down'}

        if command == 'chat':
            return self._handle_chat(params)

        if command == 'update_emotion':
            return self._handle_emotion(params)

        if command == 'start_speech':
            return self._handle_start_speech()

        if command == 'stop_speech':
            return self._handle_stop_speech()

        if command in self.handlers:
            return self.handlers[command](params)

        return {'error': f'Unknown command: {command}'}

    def _handle_chat(self, params: Dict[str, Any]) -> Dict[str, Any]:
        from milkchan.desktop.services import ai_client

        user_message = params.get('message', '')
        history = params.get('history', [])
        username = params.get('username', 'User')

        try:
            response, emotion = ai_client.chat_respond(
                user_message=user_message,
                history=history,
                username=username
            )

            if emotion and self.sprite_window:
                try:
                    from PyQt5.QtCore import QMetaObject, Qt, Q_ARG
                    emotion_data = emotion.get('emotion', [])
                    if emotion_data:
                        self.sprite_window._pending_emotion = emotion_data
                        QMetaObject.invokeMethod(
                            self.sprite_window,
                            '_apply_pending_emotion',
                            Qt.QueuedConnection
                        )
                        QMetaObject.invokeMethod(
                            self.sprite_window,
                            'start_speech_animation',
                            Qt.QueuedConnection
                        )
                except Exception as e:
                    logger.warning(f"Could not update sprite: {e}")

            return {
                'status': 'ok',
                'response': response,
                'emotion': emotion
            }
        except Exception as e:
            return {'error': str(e)}

    def _handle_emotion(self, params: Dict[str, Any]) -> Dict[str, Any]:
        emotion = params.get('emotion', [])
        if self.sprite_window and emotion:
            try:
                from PyQt5.QtCore import QMetaObject, Qt
                self.sprite_window._pending_emotion = emotion
                QMetaObject.invokeMethod(
                    self.sprite_window,
                    '_apply_pending_emotion',
                    Qt.QueuedConnection
                )
                return {'status': 'ok'}
            except Exception as e:
                return {'error': str(e)}
        return {'error': 'No sprite window or emotion'}

    def _handle_start_speech(self) -> Dict[str, Any]:
        if self.sprite_window:
            try:
                from PyQt5.QtCore import QMetaObject, Qt
                QMetaObject.invokeMethod(
                    self.sprite_window,
                    'start_speech_animation',
                    Qt.QueuedConnection
                )
                return {'status': 'ok'}
            except Exception as e:
                return {'error': str(e)}
        return {'error': 'No sprite window'}

    def _handle_stop_speech(self) -> Dict[str, Any]:
        if self.sprite_window:
            try:
                from PyQt5.QtCore import QMetaObject, Qt
                QMetaObject.invokeMethod(
                    self.sprite_window,
                    'stop_speech_animation',
                    Qt.QueuedConnection
                )
                return {'status': 'ok'}
            except Exception as e:
                return {'error': str(e)}
        return {'error': 'No sprite window'}


_ipc_server: Optional[IPCServer] = None


def get_ipc_server() -> IPCServer:
    global _ipc_server
    if _ipc_server is None:
        _ipc_server = IPCServer()
    return _ipc_server


def send_to_milkchan(command: str, params: Dict[str, Any] = None, port: int = DEFAULT_PORT) -> Dict[str, Any]:
    """Send a command to the MilkChan IPC server (used by terminal_chat)"""
    if params is None:
        params = {}

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(120.0)
        sock.connect(('127.0.0.1', port))

        message = json.dumps({'command': command, 'params': params})
        sock.sendall((message + '\n').encode('utf-8'))

        response = b''
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk
            if b'\n' in response:
                break

        sock.close()
        return json.loads(response.decode('utf-8').strip())
    except Exception as e:
        return {'error': str(e)}
