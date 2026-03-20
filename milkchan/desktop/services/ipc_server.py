"""
IPC Server for MilkChan

Provides a local socket server for external processes (like terminal_chat)
to communicate with the main MilkChan application.

Supports scalable streaming with queues for real-time updates.
"""

import json
import socket
import threading
import logging
import time
import queue
from typing import Callable, Dict, Any, Optional, List
from collections import defaultdict

from milkchan.desktop.services.stream_broker import StreamEventBroker, EventType

logger = logging.getLogger(__name__)

DEFAULT_PORT = 19527
STREAM_PORT = 19528


class StreamQueue:
    """Legacy queue for backward compatibility."""
    
    def __init__(self, maxsize: int = 100):
        self._queue = queue.Queue(maxsize=maxsize)
        self._active = False
        self._lock = threading.Lock()
        
    def start(self):
        with self._lock:
            self._active = True
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
    
    def stop(self):
        with self._lock:
            self._active = False
    
    def put(self, event: Dict[str, Any], block: bool = False, timeout: float = 0.1) -> bool:
        with self._lock:
            if not self._active:
                return False
        try:
            self._queue.put(event, block=block, timeout=timeout)
            return True
        except queue.Full:
            return False
    
    def get(self, block: bool = True, timeout: float = 0.1) -> Optional[Dict[str, Any]]:
        try:
            return self._queue.get(block=block, timeout=timeout)
        except queue.Empty:
            return None
    
    def is_active(self) -> bool:
        with self._lock:
            return self._active


class IPCServer:
    def __init__(self, port: int = DEFAULT_PORT):
        self.port = port
        self.server_socket: Optional[socket.socket] = None
        self.running = False
        self.handlers: Dict[str, Callable] = {}
        self._thread: Optional[threading.Thread] = None
        self.sprite_window = None
        self._stream_thread: Optional[threading.Thread] = None
        self._tui_active = False
        
        # Scalable streaming infrastructure
        self._tool_stream_queue = StreamQueue(maxsize=100)
        
        # Event broker for real-time streaming
        self._broker = StreamEventBroker(port=STREAM_PORT, max_subscribers=10)

    def register_handler(self, command: str, handler: Callable):
        self.handlers[command] = handler

    def set_sprite_window(self, sprite_window):
        self.sprite_window = sprite_window
        # Register IPC server as tool event callback
        try:
            from milkchan.desktop.services import ai_client
            ai_client.set_tool_event_callback(self._on_tool_event)
            logger.info("[IPC] Registered as tool event callback")
        except Exception as e:
            logger.warning(f"[IPC] Failed to register tool event callback: {e}")
    
    def _on_tool_event(self, event: Dict[str, Any]):
        """Callback for real-time tool events from ai_client."""
        # Filter out internal tools like update_sprite
        if event.get('tool_name') == 'update_sprite':
            return
        
        # Map event type to broker event type
        event_type_str = event.get('type', 'tool_end')
        if event_type_str == 'tool_start':
            broker_type = EventType.TOOL_START
        elif event_type_str == 'tool_error':
            broker_type = EventType.TOOL_ERROR
        else:
            broker_type = EventType.TOOL_END
        
        # Publish to broker for real-time streaming
        self._broker.publish(broker_type, event)

    def start(self):
        if self.running:
            return

        self.running = True
        self._thread = threading.Thread(target=self._run_server, daemon=True)
        self._thread.start()
        
        # Start the streaming broker
        self._broker.start()
        
        logger.info(f"IPC server started on port {self.port}")
        logger.info(f"Stream broker started on port {STREAM_PORT}")

    def stop(self):
        self.running = False
        
        # Stop the broker
        self._broker.stop()
        
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
            conn.settimeout(120.0)
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
                response = self._process_message(message, conn)
                conn.sendall((json.dumps(response) + '\n').encode('utf-8'))
        except Exception as e:
            logger.error(f"Client handler error: {e}")
            try:
                conn.sendall((json.dumps({'error': str(e)}) + '\n').encode('utf-8'))
            except Exception:
                pass
        finally:
            conn.close()

    def _process_message(self, message: Dict[str, Any], conn: socket.socket = None) -> Dict[str, Any]:
        command = message.get('command', '')
        params = message.get('params', {})

        if command == 'ping':
            return {'status': 'ok', 'message': 'pong'}

        if command == 'shutdown':
            return {'status': 'ok', 'message': 'shutting_down'}

        if command == 'tui_start':
            self._tui_active = True
            return {'status': 'ok', 'stream_port': STREAM_PORT}

        if command == 'tui_end':
            self._tui_active = False
            return {'status': 'ok'}

        if command == 'clear_history':
            return self._handle_clear_history()

        if command == 'sync_message':
            return self._handle_sync_message(params)

        if command == 'chat':
            return self._handle_chat(params)

        if command == 'stream_start':
            return self._handle_stream_start(params)

        if command == 'stream_text':
            return self._handle_stream_text(params)

        if command == 'stream_end':
            return self._handle_stream_end()

        if command == 'update_emotion':
            return self._handle_emotion(params)

        if command == 'start_speech':
            return self._handle_start_speech()

        if command == 'stop_speech':
            return self._handle_stop_speech()

        if command == 'get_history':
            return self._handle_get_history()

        if command == 'update_history':
            return self._handle_update_history(params)

        if command in self.handlers:
            return self.handlers[command](params)

        return {'error': f'Unknown command: {command}'}

    def _handle_chat(self, params: Dict[str, Any]) -> Dict[str, Any]:
        from milkchan.desktop.services import ai_client, memory_client
        from milkchan.core.config import load_config

        user_message = params.get('message', '')
        history = params.get('history', [])
        username = params.get('username', 'User')

        try:
            config = load_config()
            processing = config.get('processing', {})
            vision_mode = processing.get('vision_mode', 'image')
            ss_when_disabled = processing.get('screenshot_on_disabled_vision', True)

            screenshot_path = None
            should_screenshot = bool(user_message) and (
                vision_mode in ('video', 'image') or
                (not processing.get('vision_enabled', True) and ss_when_disabled)
            )

            if should_screenshot:
                try:
                    from milkchan.desktop.utils.screenshot import take_screenshot
                    rf = float(processing.get('video_resize_factor', 0.35))
                    ss = take_screenshot(rf)
                    if ss:
                        screenshot_path, width, height = ss
                        logger.info(f"[IPC] screenshot: {screenshot_path} ({width}x{height})")
                except Exception as e:
                    logger.warning(f"[IPC] screenshot failed: {e}")

            result = ai_client.chat_respond(
                user_message=user_message,
                history=history,
                username=username,
                image_path=screenshot_path
            )

            response = result.get('response', '')
            emotion = result.get('emotion')
            error = result.get('error')

            if error:
                logger.error(f"[IPC] chat error: {error.get('type')} - {error.get('message')}")
                return {
                    'status': 'error',
                    'error': error
                }

            history.append({'role': 'user', 'content': user_message})
            history.append({'role': 'assistant', 'content': response})
            memory_client.update_history(history)
            logger.info(f"[IPC] saved {len(history)} messages to history")

            if screenshot_path:
                try:
                    import os
                    if os.path.exists(screenshot_path):
                        os.remove(screenshot_path)
                except Exception:
                    pass

            return {
                'status': 'ok',
                'response': response,
                'emotion': emotion,
                'tools': result.get('tools', [])
            }
        except Exception as e:
            logger.exception(f"[IPC] chat exception: {e}")
            return {
                'status': 'error',
                'error': {
                    'type': 'ipc_error',
                    'message': str(e),
                    'details': None
                }
            }

# === Streaming Infrastructure for Scalable Real-time Updates ===

    def get_stream_port(self) -> int:
        """Get the streaming broker port."""
        return STREAM_PORT

    def get_broker_stats(self) -> Dict[str, Any]:
        """Get streaming broker statistics."""
        return self._broker.get_stats()

    def _handle_clear_history(self) -> Dict[str, Any]:
        """Clear chat history and notify all connected clients."""
        from milkchan.desktop.services import memory_client
        
        # Clear the history
        memory_client.update_history([])
        logger.info("[IPC] History cleared")
        
        # Publish clear event to streaming broker for TUI
        self._broker.publish(EventType.TOOL_START, {
            'type': 'system',
            'action': 'clear_history',
            'message': 'History cleared'
        })
        
        return {'status': 'ok', 'tui_notified': self._tui_active}

    def _handle_sync_message(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Sync a message from chatbox to TUI."""
        role = params.get('role', 'user')
        content = params.get('content', '')
        emotion = params.get('emotion')
        
        # Publish message event to streaming broker
        self._broker.publish(EventType.CHAT_RESPONSE, {
            'type': 'sync_message',
'role': role,
            'content': content,
            'emotion': emotion
        })

        logger.info(f"[IPC] Synced message to TUI: {role[:10]}...")
        return {'status': 'ok', 'tui_notified': self._tui_active}

    def notify_tui_clear_history(self):
        """Called by chatbox to notify TUI of history clear."""
        if self._tui_active:
            self._broker.publish(EventType.CHAT_RESPONSE, {
                'type': 'system',
                'action': 'clear_history'
            })
            logger.info("[IPC] Notified TUI of history clear")

    def notify_tui_new_message(self, role: str, content: str, emotion: dict = None):
        """Called by chatbox to send message to TUI."""
        if self._tui_active:
            self._broker.publish(EventType.CHAT_RESPONSE, {
                'type': 'sync_message',
                'role': role,
                'content': content,
                'emotion': emotion
            })
            logger.info(f"[IPC] Sent message to TUI: {role}")

    def _handle_stream_start(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Initialize streaming with emotion"""
        emotion = params.get('emotion', {})
        if emotion and self.sprite_window:
            emotion_data = emotion.get('emotion', [])
            if emotion_data:
                self.sprite_window._pending_emotion = emotion_data
                self._invoke_on_main_thread('_apply_pending_emotion')
            return {'status': 'ok'}

    def _handle_stream_text(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Stream text chunk - update speech animation"""
        text = params.get('text', '')
        is_final = params.get('final', False)

        if self.sprite_window:
            self._invoke_on_main_thread('start_speech_animation')

        return {'status': 'ok', 'received': len(text)}

    def _handle_stream_end(self) -> Dict[str, Any]:
        """End streaming - stop speech animation"""
        if self.sprite_window:
            self._invoke_on_main_thread('stop_speech_animation')
        return {'status': 'ok'}

    def _invoke_on_main_thread(self, method_name: str):
        """Safely invoke a method on the sprite window from background thread"""
        if self.sprite_window:
            try:
                from PyQt5.QtCore import QMetaObject, Qt
                QMetaObject.invokeMethod(
                    self.sprite_window,
                    method_name,
                    Qt.QueuedConnection
                )
            except Exception as e:
                logger.warning(f"Could not invoke {method_name}: {e}")

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
        self._invoke_on_main_thread('start_speech_animation')
        return {'status': 'ok'}

    def _handle_stop_speech(self) -> Dict[str, Any]:
        self._invoke_on_main_thread('stop_speech_animation')
        return {'status': 'ok'}

    def _handle_get_history(self) -> Dict[str, Any]:
        """Get conversation history from database"""
        try:
            from milkchan.desktop.services import memory_client
            history = memory_client.get_history()
            return {'status': 'ok', 'history': history}
        except Exception as e:
            return {'error': str(e)}

    def _handle_update_history(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Update conversation history in database"""
        try:
            from milkchan.desktop.services import memory_client
            history = params.get('history', [])
            memory_client.update_history(history)
            return {'status': 'ok'}
        except Exception as e:
            return {'error': str(e)}

    def is_tui_active(self) -> bool:
        """Check if TUI terminal is currently active"""
        return self._tui_active


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
