"""
GeezerAid — State Manager

Manages three layers of state:
  - Session: temporary, per-conversation (user, room, history)
  - Device: per-device, persists (display, audio, mic state)
  - Household: shared, syncs via CRDT (occupancy, device registry)

Stolen from: Hermes session management + HA state machine
Replaces: no shared state between devices (each device is an island)
"""
import copy
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class StateManager:
    """Manages session, device, and household state.
    
    Usage:
        state = StateManager("gtv-kitchen", event_bus)
        state.start_session("tom")
        state.add_to_history("user", "turn on the lights")
        state.update_household("occupancy", {"kitchen": "tom"})
    """

    def __init__(self, device_id: str, event_bus, sync=None):
        self.device_id = device_id
        self.bus = event_bus
        self.sync = sync  # CRDT sync engine (optional)
        
        # Session state (temporary, per-conversation)
        self.session: dict = {}
        
        # Device state (per-device, persists)
        self.device: dict = {}
        
        # Household state (shared, local cache)
        self._household: dict = {}
        
        # Load persisted device state
        self._load_device_state()
    
    # ============================================================
    # Session State (temporary)
    # ============================================================

    def start_session(self, user: str, device_id: Optional[str] = None):
        """Start a new conversation session."""
        self.session = {
            "user": user,
            "device_id": device_id or self.device_id,
            "room": self._infer_room(device_id or self.device_id),
            "history": [],
            "started_at": time.time(),
        }
        self.bus.publish("ga.session.started", self.session)
        logger.info(f"Session started: {user} in {self.session['room']}")

    def end_session(self):
        """End the current session."""
        if self.session:
            self.bus.publish("ga.session.ended", {
                "device_id": self.device_id,
                "user": self.session.get("user"),
            })
            self.session = {}

    def add_to_history(self, role: str, text: str):
        """Add to conversation history."""
        if not self.session:
            return
        self.session["history"].append({
            "role": role,
            "text": text,
            "at": time.time(),
        })
        # Keep last 20 turns
        if len(self.session["history"]) > 20:
            self.session["history"] = self.session["history"][-20:]

    def get_current_user(self) -> Optional[str]:
        """Get current user for this device."""
        return self.session.get("user")

    def get_history(self) -> list:
        """Get conversation history."""
        return self.session.get("history", [])

    def get_context(self) -> dict:
        """Get full context for LLM routing."""
        return {
            "user": self.session.get("user"),
            "room": self.session.get("room"),
            "device_id": self.device_id,
            "history": self.session.get("history", []),
            "household": self.get_household_state(),
        }

    # ============================================================
    # Device State (per-device, persists)
    # ============================================================

    def set_device_state(self, key: str, value: Any):
        """Set a device-specific state value."""
        self.device[key] = value
        self._save_device_state()

    def get_device_state(self, key: str, default: Any = None) -> Any:
        """Get a device-specific state value."""
        return self.device.get(key, default)

    def _infer_room(self, device_id: str) -> str:
        """Infer room from device ID."""
        # e.g., "gtv-kitchen" → "kitchen"
        parts = device_id.split("-")
        return parts[-1] if len(parts) > 1 else "unknown"

    def _state_path(self) -> Path:
        """Get path to device state file."""
        state_dir = Path.home() / ".geeza" / "device_state"
        state_dir.mkdir(parents=True, exist_ok=True)
        return state_dir / f"{self.device_id}.json"

    def _load_device_state(self):
        """Load persisted device state."""
        path = self._state_path()
        if path.exists():
            try:
                self.device = json.loads(path.read_text())
            except Exception as e:
                logger.warning(f"Failed to load device state: {e}")
                self.device = {}

    def _save_device_state(self):
        """Persist device state."""
        path = self._state_path()
        try:
            path.write_text(json.dumps(self.device, indent=2))
        except Exception as e:
            logger.warning(f"Failed to save device state: {e}")

    # ============================================================
    # Household State (shared, syncs via CRDT)
    # ============================================================

    def update_household(self, key: str, value: Any):
        """Update household state (syncs to all devices)."""
        if self.sync:
            self.sync.set(key, value)
        else:
            # Local-only fallback
            self._household[key] = value
            self.bus.publish("ga.household.change", {"key": key, "value": value})

    def get_household_state(self) -> dict:
        """Get full household state."""
        if self.sync:
            return self.sync.get_all()
        return self._household

    def get_occupancy(self) -> dict:
        """Get room occupancy."""
        return self.get_household_state().get("occupancy", {})

    def set_occupancy(self, room: str, user: str):
        """Set room occupancy."""
        occ = self.get_occupancy()
        occ[room] = user
        self.update_household("occupancy", occ)
        self.bus.publish("ga.occupancy.change", {"room": room, "user": user})
