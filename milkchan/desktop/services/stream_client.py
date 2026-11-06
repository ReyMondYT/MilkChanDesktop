"""Receive the app's live events in the terminal chat, reconnecting when dropped."""

import json
import logging
import socket
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class ConnectionState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"


@dataclass
class StreamConfig:
    host: str = '127.0.0.1'
    port: int = 19528
    reconnect_delay: float = 1.0
    max_reconnect_attempts: int = 5
    heartbeat_interval: float = 5.0
    receive_timeout: float = 10.0


class StreamClient:
    def __init__(self, config: Optional[StreamConfig] = None, token: str = '',
                 on_event: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.config = config or StreamConfig()
        self.token = token
        self.on_event = on_event
        self._socket: Optional[socket.socket] = None
        self._state = ConnectionState.DISCONNECTED
        self._running = False
        self._threads: List[threading.Thread] = []
        self._last_sequence = 0
        self._reconnect_attempts = 0

    def connect(self, filters: Optional[List[str]] = None) -> bool:
        """Start receiving; True once connected within five seconds."""
        if self._running:
            return True
        self._running = True
        self._state = ConnectionState.CONNECTING
        self._threads = [threading.Thread(target=self._run_client, args=(filters,), daemon=True),
                         threading.Thread(target=self._send_heartbeats, daemon=True)]
        for thread in self._threads:
            thread.start()
        deadline = time.time() + 5.0
        while time.time() < deadline:
            if self._state in (ConnectionState.CONNECTED, ConnectionState.DISCONNECTED):
                return self._state == ConnectionState.CONNECTED
            time.sleep(0.1)
        return False

    def disconnect(self):
        self._running = False
        if self._socket:
            try:
                self._socket.sendall((json.dumps({'type': 'disconnect'}) + '\n').encode('utf-8'))
                self._socket.close()
            except OSError:
                pass
        self._socket = None
        self._state = ConnectionState.DISCONNECTED
        for thread in self._threads:
            thread.join(timeout=2)

    def _run_client(self, filters: Optional[List[str]]):
        while self._running:
            try:
                self._socket = socket.create_connection((self.config.host, self.config.port),
                                                        timeout=self.config.receive_timeout)
                request = {'token': self.token, 'last_sequence': self._last_sequence, 'filters': filters or []}
                self._socket.sendall((json.dumps(request) + '\n').encode('utf-8'))
                self._state = ConnectionState.CONNECTED
                self._reconnect_attempts = 0
                buffer = b''
                while self._running:
                    try:
                        data = self._socket.recv(4096)
                    except socket.timeout:
                        continue
                    if not data:
                        break
                    buffer += data
                    while b'\n' in buffer:
                        line, buffer = buffer.split(b'\n', 1)
                        if line:
                            try:
                                self._handle_event(json.loads(line.decode('utf-8')))
                            except ValueError:
                                pass
            except OSError as exc:
                logger.debug("[StreamClient] Connection error: %s", exc)
            self._state = ConnectionState.DISCONNECTED
            if not self._running:
                break
            self._reconnect_attempts += 1
            if self._reconnect_attempts > self.config.max_reconnect_attempts:
                logger.warning("[StreamClient] Max reconnection attempts reached")
                break
            self._state = ConnectionState.RECONNECTING
            time.sleep(self.config.reconnect_delay * self._reconnect_attempts)
        self._running = False
        self._state = ConnectionState.DISCONNECTED

    def _handle_event(self, event: Dict[str, Any]):
        sequence = event.get('sequence')
        if isinstance(sequence, int) and sequence > self._last_sequence:
            self._last_sequence = sequence
        if self.on_event:
            try:
                self.on_event(event)
            except Exception as exc:  # a display bug must not drop the connection
                logger.warning("[StreamClient] Event callback error: %s", exc)

    def _send_heartbeats(self):
        while self._running:
            time.sleep(self.config.heartbeat_interval)
            if self._socket and self._state == ConnectionState.CONNECTED:
                try:
                    self._socket.sendall((json.dumps({'type': 'heartbeat'}) + '\n').encode('utf-8'))
                except OSError:
                    pass
