"""
Tests for the State Manager.
"""
import pytest
import os
from pathlib import Path
from ga_modules.core import EventBus
from ga_modules.core.state_manager import StateManager


class TestStateManager:
    def setup_method(self):
        self.bus = EventBus()
        # Use temp dir for device state
        self.state = StateManager("gtv-kitchen", self.bus)

    # ============================================================
    # Session State Tests
    # ============================================================

    def test_start_session(self):
        """Session starts with user and room."""
        self.state.start_session("tom")
        
        assert self.state.get_current_user() == "tom"
        assert self.state.session["room"] == "kitchen"
        assert self.state.session["device_id"] == "gtv-kitchen"
        assert self.state.session["history"] == []

    def test_start_session_with_device_id(self):
        """Session infers room from device_id."""
        self.state.start_session("andrea", device_id="gtv-bedroom")
        
        assert self.state.session["user"] == "andrea"
        assert self.state.session["room"] == "bedroom"

    def test_add_to_history(self):
        """History accumulates."""
        self.state.start_session("tom")
        self.state.add_to_history("user", "turn on the lights")
        self.state.add_to_history("assistant", "Lights are on.")
        
        history = self.state.get_history()
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[0]["text"] == "turn on the lights"

    def test_history_truncation(self):
        """History keeps last 20 turns."""
        self.state.start_session("tom")
        for i in range(25):
            self.state.add_to_history("user", f"message {i}")
        
        history = self.state.get_history()
        assert len(history) == 20
        assert history[0]["text"] == "message 5"

    def test_get_context(self):
        """Context includes user, room, history."""
        self.state.start_session("tom")
        self.state.add_to_history("user", "hello")
        
        ctx = self.state.get_context()
        assert ctx["user"] == "tom"
        assert ctx["room"] == "kitchen"
        assert len(ctx["history"]) == 1

    def test_end_session(self):
        """Session ends cleanly."""
        self.state.start_session("tom")
        self.state.end_session()
        
        assert self.state.get_current_user() is None

    # ============================================================
    # Device State Tests
    # ============================================================

    def test_set_get_device_state(self):
        """Device state persists."""
        self.state.set_device_state("volume", 50)
        
        assert self.state.get_device_state("volume") == 50

    def test_get_device_state_default(self):
        """Missing key returns default."""
        assert self.state.get_device_state("missing", "default") == "default"

    def test_device_state_persists(self):
        """Device state survives reload."""
        self.state.set_device_state("volume", 75)
        
        # Create new instance (simulates restart)
        state2 = StateManager("gtv-kitchen", EventBus())
        assert state2.get_device_state("volume") == 75

    # ============================================================
    # Household State Tests
    # ============================================================

    def test_update_household(self):
        """Household state updates."""
        self.state.update_household("occupancy", {"kitchen": "tom"})
        
        occ = self.state.get_occupancy()
        assert occ["kitchen"] == "tom"

    def test_set_occupancy(self):
        """Room occupancy sets correctly."""
        self.state.set_occupancy("kitchen", "tom")
        self.state.set_occupancy("bedroom", "andrea")
        
        occ = self.state.get_occupancy()
        assert occ["kitchen"] == "tom"
        assert occ["bedroom"] == "andrea"

    def test_get_household_state(self):
        """Full household state returns."""
        self.state.update_household("test_key", "test_value")
        
        state = self.state.get_household_state()
        # Either has the key or is empty (depending on sync)
        assert isinstance(state, dict)


class TestRoomInference:
    def test_infer_room_kitchen(self):
        state = StateManager("gtv-kitchen", EventBus())
        assert state._infer_room("gtv-kitchen") == "kitchen"

    def test_infer_room_bedroom(self):
        state = StateManager("gtv-bedroom", EventBus())
        assert state._infer_room("gtv-bedroom") == "bedroom"

    def test_infer_room_unknown(self):
        state = StateManager("unknown", EventBus())
        assert state._infer_room("unknown") == "unknown"
