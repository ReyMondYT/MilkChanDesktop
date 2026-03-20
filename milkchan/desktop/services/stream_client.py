"""
Stream Client for TUI - Real-time Event Receiver

Connects to the StreamEventBroker and displays events as they occur.
Supports automatic reconnection and event buffering.
"""

import json
import socket
import time
import threading
import logging
from typing import Callable, Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ConnectionState(Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"


@dataclass
class StreamConfig:
    """Configuration for stream client."""
    host: str = '127.0.0.1'
    port: int = 19528
    reconnect_delay: float = 1.0
    max_reconnect_attempts: int = 5
    heartbeat_interval: float = 5.0
    receive_timeout: float = 10.0
    buffer_size: int = 100


class StreamClient:
    """
    Real-time streaming client with automatic reconnection.
    
    Features:
    - Non-blocking event reception
    - Automatic reconnection on disconnect
    - Event buffering for missed events
    - Heartbeat monitoring
    - Event filtering
    """
    
    def __init__(self, config: StreamConfig = None, 
                 on_event: Callable[[Dict[str, Any]], None] = None,
                 on_connect: Callable[[], None] = None,
                 on_disconnect: Callable[[], None] = None):
        self.config = config or StreamConfig()
        self.on_event = on_event
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        
        self._socket: Optional[socket.socket] = None
        self._state = ConnectionState.DISCONNECTED
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._heartbeat_thread: Optional[threading.Thread] = None
        
        self._last_sequence = 0
        self._reconnect_attempts = 0
        self._events_received = 0
        self._events_buffer: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
    
    @property
    def state(self) -> ConnectionState:
        return self._state
    
    @property
    def is_connected(self) -> bool:
        return self._state == ConnectionState.CONNECTED
    
    def connect(self, filters: List[str] = None, last_sequence: int = 0) -> bool:
        """
        Connect to the stream broker.
        
        Args:
            filters: List of event types to receive (empty = all)
            last_sequence: Resume from this sequence number
        
        Returns:
            True if connection successful
        """
        if self._running:
            return True
        
        self._last_sequence = last_sequence
        self._running = True
        self._state = ConnectionState.CONNECTING
        
        # Start connection thread
        self._thread = threading.Thread(target=self._run_client, args=(filters,), daemon=True)
        self._thread.start()
        
        # Start heartbeat thread
        self._heartbeat_thread = threading.Thread(target=self._send_heartbeats, daemon=True)
        self._heartbeat_thread.start()
        
        # Wait for connection
        timeout = 5.0
        start = time.time()
        while time.time() - start < timeout:
            if self._state == ConnectionState.CONNECTED:
                return True
            if self._state == ConnectionState.DISCONNECTED:
                return False
            time.sleep(0.1)
        
        return False
    
    def disconnect(self):
        """Disconnect from the stream broker."""
        self._running = False
        
        if self._socket:
            try:
                # Send disconnect message
                msg = json.dumps({'type': 'disconnect'})
                self._socket.sendall((msg + '\n').encode('utf-8'))
                self._socket.close()
            except Exception:
                pass
        
        self._socket = None
        self._state = ConnectionState.DISCONNECTED
        
        if self._thread:
            self._thread.join(timeout=2)
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=2)
    
    def get_buffered_events(self) -> List[Dict[str, Any]]:
        """Get and clear buffered events."""
        with self._lock:
            events = self._events_buffer.copy()
            self._events_buffer.clear()
            return events
    
    def _run_client(self, filters: List[str] = None):
        """Main client loop with reconnection."""
        while self._running:
            try:
                # Connect
                self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._socket.settimeout(self.config.receive_timeout)
                self._socket.connect((self.config.host, self.config.port))
                
                # Send subscription request
                request = {
                    'last_sequence': self._last_sequence,
                    'filters': filters or []
                }
                self._socket.sendall((json.dumps(request) + '\n').encode('utf-8'))
                
                self._state = ConnectionState.CONNECTED
                self._reconnect_attempts = 0
                
                if self.on_connect:
                    self.on_connect()
                
                # Receive events
                buffer = b''
                while self._running:
                    try:
                        data = self._socket.recv(4096)
                        if not data:
                            break
                        
                        buffer += data
                        
                        # Process complete messages
                        while b'\n' in buffer:
                            line, buffer = buffer.split(b'\n', 1)
                            if line:
                                try:
                                    event = json.loads(line.decode('utf-8'))
                                    self._handle_event(event)
                                except json.JSONDecodeError:
                                    pass
                    
                    except socket.timeout:
                        continue
                    except Exception:
                        break
                
            except Exception as e:
                logger.debug(f"[StreamClient] Connection error: {e}")
            
            # Disconnected
            self._state = ConnectionState.DISCONNECTED
            
            if self.on_disconnect:
                self.on_disconnect()
            
            # Attempt reconnection
            if self._running:
                self._reconnect_attempts += 1
                if self._reconnect_attempts > self.config.max_reconnect_attempts:
                    logger.warning("[StreamClient] Max reconnection attempts reached")
                    break
                
                self._state = ConnectionState.RECONNECTING
                time.sleep(self.config.reconnect_delay * self._reconnect_attempts)
        
        self._running = False
        self._state = ConnectionState.DISCONNECTED
    
    def _handle_event(self, event: Dict[str, Any]):
        """Handle a received event."""
        self._events_received += 1
        self._last_sequence = event.get('sequence', self._last_sequence)
        
        # Buffer event
        with self._lock:
            if len(self._events_buffer) < self.config.buffer_size:
                self._events_buffer.append(event)
        
        # Call callback
        if self.on_event:
            try:
                self.on_event(event)
            except Exception as e:
                logger.warning(f"[StreamClient] Event callback error: {e}")
    
    def _send_heartbeats(self):
        """Send heartbeat messages to keep connection alive."""
        while self._running:
            time.sleep(self.config.heartbeat_interval)
            
            if self._socket and self._state == ConnectionState.CONNECTED:
                try:
                    msg = json.dumps({'type': 'heartbeat', 'timestamp': time.time()})
                    self._socket.sendall((msg + '\n').encode('utf-8'))
                except Exception:
                    pass
    
    def get_stats(self) -> Dict[str, Any]:
        """Get client statistics."""
        return {
            'state': self._state.value,
            'events_received': self._events_received,
            'last_sequence': self._last_sequence,
            'reconnect_attempts': self._reconnect_attempts,
            'buffered_events': len(self._events_buffer)
        }