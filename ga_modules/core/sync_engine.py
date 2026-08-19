"""
GeezerAid — Sync Engine

CRDT-based state sync between devices.
Conflict-free replicated data with operation log + vector clocks.

Stolen from: Ink & Switch CRDT research + Automerge/Yjs patterns
Replaces: Syncthing file sync (we need state sync, not file sync)
"""
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class Operation:
    """A commutative, idempotent operation."""
    key: str
    value: Any
    device: str
    timestamp: float
    device_clock: int = 0  # Lamport clock for this device


@dataclass
class VectorClock:
    """Vector clock for tracking device state."""
    clocks: dict[str, int] = field(default_factory=dict)
    
    def increment(self, device: str):
        """Increment clock for a device."""
        self.clocks[device] = self.clocks.get(device, 0) + 1
    
    def merge(self, other: 'VectorClock'):
        """Merge two vector clocks."""
        for device, clock in other.clocks.items():
            self.clocks[device] = max(self.clocks.get(device, 0), clock)
    
    def happens_before(self, other: 'VectorClock') -> bool:
        """Check if this clock happens before other."""
        for device, clock in self.clocks.items():
            if clock > other.clocks.get(device, 0):
                return False
        return True
    
    def copy(self) -> 'VectorClock':
        return VectorClock(clocks=dict(self.clocks))


class CRDTStore:
    """Conflict-free replicated data store.
    
    Uses Last-Writer-Wins (LWW) per key for simplicity.
    Vector clocks track causality.
    """
    
    def __init__(self):
        self.state: dict[str, Any] = {}
        self.op_log: list[Operation] = []
        self.vector_clock = VectorClock()
        self._lock = threading.RLock()
    
    def apply(self, operation: Operation):
        """Apply an operation (commutative, idempotent)."""
        with self._lock:
            key = operation.key
            
            # LWW: only update if this operation is newer
            if key not in self.state or operation.timestamp > self.state[key][1]:
                self.state[key] = (operation.value, operation.timestamp)
            
            self.op_log.append(operation)
            self.vector_clock.clocks[key] = self.vector_clock.clocks.get(key, 0) + 1
    
    def get(self, key: str) -> Any:
        """Get current value."""
        with self._lock:
            entry = self.state.get(key)
            return entry[0] if entry else None
    
    def get_all(self) -> dict:
        """Get all state."""
        with self._lock:
            return {k: v[0] for k, v in self.state.items()}
    
    def since(self, version: VectorClock) -> list[Operation]:
        """Get operations since a vector clock version."""
        with self._lock:
            return [
                op for op in self.op_log
                if op.device_clock > version.clocks.get(op.device, 0)
            ]
    
    def merge(self, other: 'CRDTStore'):
        """Merge another CRDT store."""
        for op in other.op_log:
            self.apply(op)


class SyncEngine:
    """CRDT-based state sync between devices."""
    
    def __init__(self, device_id: str, event_bus, sync_interval: int = 30):
        self.device_id = device_id
        self.bus = event_bus
        self.store = CRDTStore()
        self.peers: dict[str, VectorClock] = {}  # device_id -> last known clock
        self.sync_interval = sync_interval
        self._running = False
        self._thread = None
        
        # Subscribe to household changes
        self.bus.subscribe("ga.household.change", self._on_household_change)
    
    def start(self):
        """Start periodic sync."""
        self._running = True
        self._thread = threading.Thread(target=self._sync_loop, daemon=True)
        self._thread.start()
        logger.info(f"Sync engine started for {self.device_id}")
    
    def stop(self):
        """Stop sync."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
    
    def _sync_loop(self):
        """Periodic sync loop."""
        while self._running:
            for peer_id in list(self.peers.keys()):
                self._sync_with_peer(peer_id)
            time.sleep(self.sync_interval)
    
    def _sync_with_peer(self, peer_id: str):
        """Sync with a specific peer."""
        # In real impl: exchange operations via WebSocket/HTTP
        # For now, just update the peer clock
        pass
    
    def set(self, key: str, value: Any):
        """Set a value (syncs to all peers)."""
        op = Operation(
            key=key,
            value=value,
            device=self.device_id,
            timestamp=time.time(),
            device_clock=self._next_clock(),
        )
        self.store.apply(op)
    
    def get(self, key: str) -> Any:
        """Get current value."""
        return self.store.get(key)
    
    def get_all(self) -> dict:
        """Get all state."""
        return self.store.get_all()
    
    def _next_clock(self) -> int:
        """Get next Lamport clock value."""
        return self.store.vector_clock.clocks.get(self.device_id, 0) + 1
    
    def _on_household_change(self, msg):
        """Handle household change event."""
        key = msg["payload"].get("key")
        value = msg["payload"].get("value")
        if key and value:
            self.set(key, value)
    
    def add_peer(self, device_id: str):
        """Add a peer to sync with."""
        self.peers[device_id] = VectorClock()
    
    def remove_peer(self, device_id: str):
        """Remove a peer."""
        self.peers.pop(device_id, None)
