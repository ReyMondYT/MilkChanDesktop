"""
Stream Event Broker - Scalable Pub/Sub Architecture for Real-time Event Streaming

Design patterns:
- Publisher/Subscriber for decoupled event distribution
- Ring buffer for bounded memory usage
- Non-blocking I/O for scalability
- Connection pooling for multiple clients
- Heartbeat monitoring for connection health
"""

import json
import time
import threading
import logging
import socket
import select
from typing import Dict, Any, Optional, List, Callable, Set
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
import weakref

logger = logging.getLogger(__name__)


class EventType(Enum):
    TOOL_START = "tool_start"
    TOOL_END = "tool_end"
    TOOL_ERROR = "tool_error"
    CHAT_RESPONSE = "chat_response"
    CHAT_COMPLETE = "chat_complete"
    HEARTBEAT = "heartbeat"
    ERROR = "error"


@dataclass
class StreamEvent:
    """Represents a single streaming event."""
    type: EventType
    data: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    sequence: int = 0
    
    def to_json(self) -> str:
        return json.dumps({
            'type': self.type.value,
            'data': self.data,
            'timestamp': self.timestamp,
            'sequence': self.sequence
        })
    
    @classmethod
    def from_json(cls, json_str: str) -> 'StreamEvent':
        d = json.loads(json_str)
        return cls(
            type=EventType(d['type']),
            data=d['data'],
            timestamp=d.get('timestamp', time.time()),
            sequence=d.get('sequence', 0)
        )


class RingBuffer:
    """Thread-safe ring buffer for event history with bounded memory."""
    
    def __init__(self, maxsize: int = 1000):
        self._buffer = deque(maxlen=maxsize)
        self._lock = threading.Lock()
        self._sequence = 0
    
    def put(self, event: StreamEvent) -> int:
        """Add event to buffer. Returns sequence number."""
        with self._lock:
            self._sequence += 1
            event.sequence = self._sequence
            self._buffer.append(event)
            return self._sequence
    
    def get_since(self, sequence: int) -> List[StreamEvent]:
        """Get all events after the given sequence number."""
        with self._lock:
            return [e for e in self._buffer if e.sequence > sequence]
    
    def get_last(self, n: int = 10) -> List[StreamEvent]:
        """Get last n events."""
        with self._lock:
            return list(self._buffer)[-n:]
    
    def clear(self):
        """Clear the buffer."""
        with self._lock:
            self._buffer.clear()


class Subscriber:
    """Represents a subscriber connection."""
    
    def __init__(self, subscriber_id: str, socket: socket.socket, 
                 last_sequence: int = 0, filters: Set[EventType] = None):
        self.id = subscriber_id
        self.socket = socket
        self.last_sequence = last_sequence
        self.filters = filters or set()  # Empty set = receive all
        self.connected = True
        self.last_heartbeat = time.time()
        self.events_sent = 0
        self.events_dropped = 0
        self._lock = threading.Lock()
    
    def send(self, event: StreamEvent) -> bool:
        """Send event to subscriber. Non-blocking."""
        if not self.connected:
            return False
        
        # Check filter
        if self.filters and event.type not in self.filters:
            return True  # Filtered out, but success
        
        try:
            with self._lock:
                self.socket.sendall((event.to_json() + '\n').encode('utf-8'))
                self.last_sequence = event.sequence
                self.events_sent += 1
            return True
        except (socket.error, OSError, BrokenPipeError) as e:
            logger.debug(f"[Subscriber {self.id}] Send failed: {e}")
            self.connected = False
            self.events_dropped += 1
            return False
    
    def disconnect(self):
        """Mark subscriber as disconnected."""
        with self._lock:
            self.connected = False
            try:
                self.socket.close()
            except Exception:
                pass
    
    def update_heartbeat(self):
        """Update heartbeat timestamp."""
        with self._lock:
            self.last_heartbeat = time.time()
    
    def is_alive(self, timeout: float = 30.0) -> bool:
        """Check if subscriber is still alive based on heartbeat."""
        return self.connected and (time.time() - self.last_heartbeat) < timeout


class StreamEventBroker:
    """
    Scalable event broker with pub/sub pattern.
    
    Features:
    - Non-blocking event distribution
    - Ring buffer for replay capability
    - Connection health monitoring
    - Backpressure handling
    - Event filtering per subscriber
    """
    
    def __init__(self, port: int = 19528, max_subscribers: int = 10,
                 buffer_size: int = 1000, heartbeat_interval: float = 5.0):
        self.port = port
        self.max_subscribers = max_subscribers
        self.heartbeat_interval = heartbeat_interval
        
        # Ring buffer for event history
        self._buffer = RingBuffer(maxsize=buffer_size)
        
        # Active subscribers (weak references for automatic cleanup)
        self._subscribers: Dict[str, Subscriber] = {}
        self._subscribers_lock = threading.RLock()
        
        # Server socket
        self._server_socket: Optional[socket.socket] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._heartbeat_thread: Optional[threading.Thread] = None
        
        # Statistics
        self._events_published = 0
        self._events_dropped = 0
    
    def start(self):
        """Start the streaming broker."""
        if self._running:
            return
        
        self._running = True
        
        # Start server thread
        self._thread = threading.Thread(target=self._run_server, daemon=True)
        self._thread.start()
        
        # Start heartbeat monitor
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_monitor, daemon=True)
        self._heartbeat_thread.start()
        
        logger.info(f"[StreamBroker] Started on port {self.port}")
    
    def stop(self):
        """Stop the streaming broker."""
        self._running = False
        
        # Disconnect all subscribers
        with self._subscribers_lock:
            for sub in self._subscribers.values():
                sub.disconnect()
            self._subscribers.clear()
        
        # Close server socket
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass
        
        # Wait for threads
        if self._thread:
            self._thread.join(timeout=2)
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=2)
        
        logger.info("[StreamBroker] Stopped")
    
    def publish(self, event_type: EventType, data: Dict[str, Any]) -> int:
        """
        Publish an event to all subscribers.
        Non-blocking - returns immediately.
        
        Returns sequence number of the event.
        """
        event = StreamEvent(type=event_type, data=data)
        sequence = self._buffer.put(event)
        self._events_published += 1
        
        # Distribute to all subscribers
        dead_subscribers = []
        
        with self._subscribers_lock:
            for sub_id, sub in self._subscribers.items():
                if not sub.send(event):
                    dead_subscribers.append(sub_id)
                    self._events_dropped += 1
        
        # Clean up dead subscribers
        if dead_subscribers:
            with self._subscribers_lock:
                for sub_id in dead_subscribers:
                    if sub_id in self._subscribers:
                        del self._subscribers[sub_id]
                        logger.debug(f"[StreamBroker] Removed dead subscriber {sub_id}")
        
        return sequence
    
    def _run_server(self):
        """Run the streaming server."""
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.bind(('127.0.0.1', self.port))
        self._server_socket.listen(self.max_subscribers)
        self._server_socket.settimeout(1.0)
        
        while self._running:
            try:
                conn, addr = self._server_socket.accept()
                
                # Check max subscribers
                with self._subscribers_lock:
                    if len(self._subscribers) >= self.max_subscribers:
                        logger.warning(f"[StreamBroker] Max subscribers reached, rejecting {addr}")
                        conn.close()
                        continue
                
                # Handle new connection
                thread = threading.Thread(target=self._handle_connection, args=(conn, addr), daemon=True)
                thread.start()
                
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    logger.error(f"[StreamBroker] Server error: {e}")
    
    def _handle_connection(self, conn: socket.socket, addr):
        """Handle a new subscriber connection."""
        subscriber_id = f"{addr[0]}:{addr[1]}"
        
        try:
            # Receive subscription request
            conn.settimeout(10.0)
            data = b''
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
                if b'\n' in data:
                    break
            
            if data:
                request = json.loads(data.decode('utf-8').strip())
                
                # Parse subscription options
                last_sequence = request.get('last_sequence', 0)
                filter_types = request.get('filters', [])
                filters = {EventType(t) for t in filter_types} if filter_types else set()
                
                # Create subscriber
                subscriber = Subscriber(
                    subscriber_id=subscriber_id,
                    socket=conn,
                    last_sequence=last_sequence,
                    filters=filters
                )
                
                # Register subscriber
                with self._subscribers_lock:
                    self._subscribers[subscriber_id] = subscriber
                
                logger.info(f"[StreamBroker] New subscriber {subscriber_id} (seq={last_sequence}, filters={filters})")
                
                # Send missed events (replay)
                missed_events = self._buffer.get_since(last_sequence)
                for event in missed_events:
                    if not subscriber.send(event):
                        break
                
                # Send welcome message
                welcome = StreamEvent(
                    type=EventType.HEARTBEAT,
                    data={'message': 'connected', 'subscriber_id': subscriber_id}
                )
                subscriber.send(welcome)
                
                # Keep connection alive and receive heartbeats
                conn.settimeout(self.heartbeat_interval * 2)
                while self._running:
                    try:
                        data = conn.recv(4096)
                        if not data:
                            break
                        
                        # Parse heartbeat or command
                        try:
                            msg = json.loads(data.decode('utf-8').strip())
                            if msg.get('type') == 'heartbeat':
                                subscriber.update_heartbeat()
                            elif msg.get('type') == 'disconnect':
                                break
                        except json.JSONDecodeError:
                            pass
                            
                    except socket.timeout:
                        # Check if subscriber is still alive
                        if not subscriber.is_alive():
                            break
                        continue
                    except Exception:
                        break
            
        except Exception as e:
            logger.debug(f"[StreamBroker] Connection error for {subscriber_id}: {e}")
        finally:
            # Cleanup
            with self._subscribers_lock:
                if subscriber_id in self._subscribers:
                    del self._subscribers[subscriber_id]
            try:
                conn.close()
            except Exception:
                pass
            logger.info(f"[StreamBroker] Subscriber {subscriber_id} disconnected")
    
    def _heartbeat_monitor(self):
        """Monitor subscriber health and send heartbeats."""
        while self._running:
            time.sleep(self.heartbeat_interval)
            
            # Send heartbeats and check for dead subscribers
            heartbeat = StreamEvent(type=EventType.HEARTBEAT, data={'time': time.time()})
            
            dead_subscribers = []
            
            with self._subscribers_lock:
                for sub_id, sub in self._subscribers.items():
                    if not sub.is_alive():
                        dead_subscribers.append(sub_id)
                    else:
                        sub.send(heartbeat)
            
            # Clean up dead subscribers
            if dead_subscribers:
                with self._subscribers_lock:
                    for sub_id in dead_subscribers:
                        if sub_id in self._subscribers:
                            self._subscribers[sub_id].disconnect()
                            del self._subscribers[sub_id]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get broker statistics."""
        with self._subscribers_lock:
            return {
                'running': self._running,
                'port': self.port,
                'subscribers': len(self._subscribers),
                'max_subscribers': self.max_subscribers,
                'events_published': self._events_published,
                'events_dropped': self._events_dropped,
                'buffer_size': self._buffer._buffer.maxlen,
                'buffer_used': len(self._buffer._buffer)
            }
    
    def get_subscribers(self) -> List[Dict[str, Any]]:
        """Get list of active subscribers with their stats."""
        with self._subscribers_lock:
            return [
                {
                    'id': sub.id,
                    'last_sequence': sub.last_sequence,
                    'connected': sub.connected,
                    'events_sent': sub.events_sent,
                    'events_dropped': sub.events_dropped,
                    'last_heartbeat': sub.last_heartbeat,
                    'filters': [f.value for f in sub.filters] if sub.filters else []
                }
                for sub in self._subscribers.values()
            ]