"""
GeezerAid — Event Bus

Pub/sub message bus that decouples modules. Each module publishes events
to topics and subscribes to topics it cares about. Modules never call each
other directly — they only know about the bus.

Stolen from: MQTT pub/sub pattern
Replaces: direct function calls between modules (which we never had, so this
          is the foundation everything else builds on).
"""
import copy
import json
import logging
import re
import threading
import time
from collections import defaultdict, deque
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# ============================================================
# Topic hierarchy (stolen from MQTT topic conventions)
# ============================================================
TOPICS = {
    # Wake and voice
    "ga.wake.detected":       "Wake word detected",
    "ga.voice.captured":      "Voice captured",
    "ga.voice.transcribed":   "Voice transcribed",
    # Cognition
    "ga.command.received":    "Command received",
    "ga.intent.matched":      "HA intent matched",
    "ga.llm.thinking":        "LLM processing",
    "ga.response.ready":      "LLM response ready",
    # Action
    "ga.tts.requested":       "TTS requested",
    "ga.tts.playing":         "TTS playing",
    "ga.display.update":      "Display update",
    # Device
    "ga.device.online":       "Device came online",
    "ga.device.offline":      "Device went offline",
    "ga.device.state":        "Device state change",
    # Household
    "ga.household.change":    "Household state changed",
    "ga.occupancy.change":    "Room occupancy changed",
    "ga.session.started":     "Session started",
    "ga.session.ended":       "Session ended",
    # Vault
    "ga.vault.change":        "Vault content changed",
    "ga.vault.synced":        "Vault sync complete",
    # Safety
    "ga.safety.blocked":      "Safety rule blocked action",
    # Weather
    "ga.weather.update":      "Weather data updated",
}


class EventBus:
    """Thread-safe pub/sub event bus.
    
    Topics support wildcards:
        ga.wake.*        — any wake event
        ga.*.detected    — any detection event
        ga.#             — all ga events
        
    Usage:
        bus = EventBus()
        bus.subscribe("ga.wake.detected", lambda msg: print(msg))
        bus.publish("ga.wake.detected", {"device_id": "kitchen", "user": "tom"})
    """

    def __init__(self, log_size: int = 1000):
        self._subscribers: dict[str, list[Callable]] = defaultdict(list)
        self._lock = threading.RLock()
        self._log: deque[dict] = deque(maxlen=log_size)
        self._running = True

    # ============================================================
    # Core pub/sub
    # ============================================================

    def publish(self, topic: str, payload: dict) -> None:
        """Publish an event to all subscribers.
        
        Args:
            topic: Topic name (e.g., "ga.wake.detected")
            payload: Event data dict
        """
        msg = {
            "topic": topic,
            "payload": copy.deepcopy(payload),  # isolate from mutation
            "timestamp": time.time(),
            "device_id": payload.get("device_id", "unknown"),
        }

        # Log the message
        with self._lock:
            self._log.append(msg)

        # Notify exact-match subscribers
        handlers = []
        with self._lock:
            handlers.extend(self._subscribers.get(topic, []))
            # Also notify wildcard subscribers (skip exact matches already handled)
            for pattern, subs in self._subscribers.items():
                if pattern != topic and self._topic_matches(pattern, topic):
                    handlers.extend(subs)
        
        # Deduplicate handlers (multiple patterns may match)
        seen = set()
        unique = []
        for h in handlers:
            if id(h) not in seen:
                seen.add(id(h))
                unique.append(h)
        handlers = unique

        # Call handlers outside the lock to avoid deadlocks
        for handler in handlers:
            try:
                handler(msg)
            except Exception as e:
                logger.error(f"Handler error on {topic}: {e}", exc_info=True)

    def subscribe(self, topic: str, handler: Callable) -> None:
        """Subscribe to a topic. Supports wildcards.
        
        Args:
            topic: Topic pattern (e.g., "ga.wake.*" or "ga.command.received")
            handler: Callback that receives the full message dict
        """
        with self._lock:
            self._subscribers[topic].append(handler)
        logger.debug(f"Subscribed to {topic}: {handler.__name__}")

    def unsubscribe(self, topic: str, handler: Callable) -> None:
        """Unsubscribe a handler from a topic."""
        with self._lock:
            if topic in self._subscribers:
                self._subscribers[topic] = [
                    h for h in self._subscribers[topic] if h is not handler
                ]

    # ============================================================
    # Topic pattern matching (stolen from MQTT wildcards)
    # ============================================================

    @staticmethod
    def _topic_matches(pattern: str, topic: str) -> bool:
        """Check if a pattern matches a topic.
        
        * matches a single level (between dots)
        # matches zero or more levels (at the end only)
        """
        if pattern == topic:
            return True
        if "*" not in pattern and "#" not in pattern:
            return False
        
        # Convert pattern to regex
        regex = pattern
        regex = regex.replace(".", r"\.")
        regex = regex.replace("*", r"[^.]+")
        regex = regex.replace("#", r".*")
        regex = f"^{regex}$"
        
        return bool(re.match(regex, topic))

    # ============================================================
    # Utilities
    # ============================================================

    def recent(self, n: int = 50) -> list[dict]:
        """Get recent messages."""
        with self._lock:
            return list(self._log)[-n:]

    def subscribers_for(self, topic: str) -> list[str]:
        """Get list of subscribed patterns (for debugging)."""
        with self._lock:
            return list(self._subscribers.keys())

    def shutdown(self):
        """Stop the bus."""
        self._running = False


# ============================================================
# Singleton instance (one bus per device)
# ============================================================
_bus: Optional[EventBus] = None
_bus_lock = threading.Lock()


def get_event_bus() -> EventBus:
    """Get the singleton event bus instance."""
    global _bus
    if _bus is None:
        with _bus_lock:
            if _bus is None:
                _bus = EventBus()
    return _bus
