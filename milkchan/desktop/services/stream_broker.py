"""Push live events (tool calls, synced chat) to terminal chat subscribers.

A subscriber sends one JSON line ``{"token", "last_sequence", "filters"}``.
Events after ``last_sequence`` are replayed from a bounded buffer, so a
client that reconnects misses nothing; a new client (sequence 0) starts now.
"""

import hmac
import json
import logging
import socket
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

MAX_REQUEST_BYTES = 64 * 1024


class EventType(Enum):
    TOOL_START = "tool_start"
    TOOL_END = "tool_end"
    TOOL_ERROR = "tool_error"
    CHAT_RESPONSE = "chat_response"
    HEARTBEAT = "heartbeat"


@dataclass
class StreamEvent:
    type: EventType
    data: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    sequence: int = 0

    def to_json(self) -> str:
        return json.dumps({'type': self.type.value, 'data': self.data,
                           'timestamp': self.timestamp, 'sequence': self.sequence})


class RingBuffer:
    """Thread-safe, bounded event history for replay."""

    def __init__(self, maxsize: int = 1000):
        self._buffer = deque(maxlen=maxsize)
        self._lock = threading.Lock()
        self.sequence = 0

    def put(self, event: StreamEvent) -> int:
        with self._lock:
            self.sequence += 1
            event.sequence = self.sequence
            self._buffer.append(event)
            return self.sequence

    def get_since(self, sequence: int) -> List[StreamEvent]:
        with self._lock:
            return [event for event in self._buffer if event.sequence > sequence]


def read_line(conn: socket.socket, limit: int = MAX_REQUEST_BYTES) -> bytes:
    """One newline-terminated message; raises ValueError past ``limit`` bytes."""
    data = b''
    while b'\n' not in data:
        chunk = conn.recv(4096)
        if not chunk:
            break
        data += chunk
        if len(data) > limit:
            raise ValueError('request too large')
    return data.split(b'\n', 1)[0]


class Subscriber:
    def __init__(self, subscriber_id: str, conn: socket.socket, filters: Set[EventType]):
        self.id = subscriber_id
        self.socket = conn
        self.filters = filters  # empty: every event
        self.connected = True
        self.last_heartbeat = time.time()
        self._lock = threading.Lock()

    def send(self, event: StreamEvent) -> bool:
        if not self.connected:
            return False
        if self.filters and event.type not in self.filters:
            return True
        try:
            with self._lock:
                self.socket.sendall((event.to_json() + '\n').encode('utf-8'))
            return True
        except OSError as exc:
            logger.debug("[Subscriber %s] Send failed: %s", self.id, exc)
            self.connected = False
            return False

    def disconnect(self):
        with self._lock:
            self.connected = False
            try:
                self.socket.close()
            except OSError:
                pass

    def is_alive(self, timeout: float = 30.0) -> bool:
        return self.connected and (time.time() - self.last_heartbeat) < timeout


class StreamEventBroker:
    def __init__(self, token: str, port: int = 19528, max_subscribers: int = 10,
                 buffer_size: int = 1000, heartbeat_interval: float = 5.0):
        self.token = token
        self.port = port
        self.max_subscribers = max_subscribers
        self.heartbeat_interval = heartbeat_interval
        self._buffer = RingBuffer(maxsize=buffer_size)
        self._subscribers: Dict[str, Subscriber] = {}
        self._subscribers_lock = threading.RLock()
        self._server_socket: Optional[socket.socket] = None
        self._running = False
        self._threads: List[threading.Thread] = []

    def start(self):
        if self._running:
            return
        self._running = True
        self._threads = [threading.Thread(target=self._run_server, daemon=True),
                         threading.Thread(target=self._heartbeat_monitor, daemon=True)]
        for thread in self._threads:
            thread.start()

    def stop(self):
        self._running = False
        with self._subscribers_lock:
            for subscriber in self._subscribers.values():
                subscriber.disconnect()
            self._subscribers.clear()
        if self._server_socket:
            try:
                self._server_socket.close()
            except OSError:
                pass
        for thread in self._threads:
            thread.join(timeout=2)

    def publish(self, event_type: EventType, data: Dict[str, Any]) -> int:
        event = StreamEvent(type=event_type, data=data)
        sequence = self._buffer.put(event)
        with self._subscribers_lock:
            for subscriber_id in [sid for sid, sub in self._subscribers.items() if not sub.send(event)]:
                del self._subscribers[subscriber_id]
        return sequence

    def _run_server(self):
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind(('127.0.0.1', self.port))
        self._server_socket.listen(self.max_subscribers)
        self._server_socket.settimeout(1.0)
        while self._running:
            try:
                conn, addr = self._server_socket.accept()
            except socket.timeout:
                continue
            except OSError as exc:
                if self._running:
                    logger.error("[StreamBroker] Server error: %s", exc)
                continue
            with self._subscribers_lock:
                full = len(self._subscribers) >= self.max_subscribers
            if full:
                logger.warning("[StreamBroker] Max subscribers reached, rejecting %s", addr)
                conn.close()
                continue
            threading.Thread(target=self._handle_connection, args=(conn, addr), daemon=True).start()

    def _handle_connection(self, conn: socket.socket, addr):
        subscriber_id = f"{addr[0]}:{addr[1]}"
        try:
            conn.settimeout(10.0)
            request = json.loads(read_line(conn).decode('utf-8'))
            if not hmac.compare_digest(str(request.get('token', '')), self.token):
                logger.warning("[StreamBroker] Rejected %s: invalid token", subscriber_id)
                return
            subscriber = Subscriber(subscriber_id, conn, {EventType(t) for t in request.get('filters') or []})
            with self._subscribers_lock:
                self._subscribers[subscriber_id] = subscriber
            last_sequence = int(request.get('last_sequence') or 0)
            if last_sequence:
                for event in self._buffer.get_since(last_sequence):
                    if not subscriber.send(event):
                        break
            # The welcome carries the current sequence so a later reconnect resumes from here.
            subscriber.send(StreamEvent(type=EventType.HEARTBEAT, sequence=self._buffer.sequence,
                                        data={'message': 'connected', 'subscriber_id': subscriber_id}))
            conn.settimeout(self.heartbeat_interval * 2)
            while self._running:
                try:
                    data = conn.recv(4096)
                except socket.timeout:
                    if not subscriber.is_alive():
                        break
                    continue
                if not data:
                    break
                for line in data.splitlines():
                    try:
                        message = json.loads(line)
                    except ValueError:
                        continue
                    if message.get('type') == 'heartbeat':
                        subscriber.last_heartbeat = time.time()
                    elif message.get('type') == 'disconnect':
                        return
        except (OSError, ValueError) as exc:
            logger.debug("[StreamBroker] Connection error for %s: %s", subscriber_id, exc)
        finally:
            with self._subscribers_lock:
                self._subscribers.pop(subscriber_id, None)
            try:
                conn.close()
            except OSError:
                pass

    def _heartbeat_monitor(self):
        while self._running:
            time.sleep(self.heartbeat_interval)
            heartbeat = StreamEvent(type=EventType.HEARTBEAT, data={'time': time.time()})
            with self._subscribers_lock:
                for subscriber_id, subscriber in list(self._subscribers.items()):
                    if subscriber.is_alive():
                        subscriber.send(heartbeat)
                    else:
                        subscriber.disconnect()
                        del self._subscribers[subscriber_id]
