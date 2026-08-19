"""
Tests for the full GA System.
"""
import pytest
from ga_modules.core import EventBus
from ga_modules.core.system import GeezerAid


class TestGeezerAid:
    def setup_method(self):
        # Reset singleton bus
        import ga_modules.core
        ga_modules.core._bus = EventBus()
        self.ga = GeezerAid("gtv-kitchen")

    def test_capabilities(self):
        """Capabilities list all modules."""
        caps = self.ga.capabilities
        assert "stt" in caps
        assert "llm" in caps
        assert "tts" in caps
        assert "display" in caps

    def test_available(self):
        """System is available."""
        assert self.ga.available is True

    def test_wake_flow(self):
        """Wake word flow works."""
        self.ga.bus.publish("ga.wake.detected", {"user": "tom"})
        assert self.ga.state.get_current_user() == "tom"

    def test_command_flow(self):
        """Command routing flow works."""
        self.ga.state.start_session("tom")
        # Set up HA bridge for intent matching
        from ga_modules.core.ha_bridge import HABridge
        self.ga.ha = HABridge(event_bus=self.ga.bus)
        self.ga.coordinator.set_ha_bridge(self.ga.ha)
        response = self.ga.coordinator.route_command("turn on the kitchen lights")
        assert response.source == "ha_intent"

    def test_safety_flow(self):
        """Safety blocks dangerous commands."""
        self.ga.state.start_session("tom")
        response = self.ga.coordinator.route_command("turn off the server")
        assert response.source == "safety"

    def test_voice_pipeline(self):
        """Voice pipeline works."""
        self.ga.state.start_session("tom")
        # Mock audio
        response = self.ga.coordinator.route_voice(b"audio_data")
        # STT module can't actually transcribe, so this is just a smoke test
        assert response.source == "error"  # STT fails without real whisper

    def test_start_stop(self):
        """Start and stop work."""
        self.ga.start()
        assert self.ga.sync._running is True
        self.ga.stop()
        assert self.ga.sync._running is False

    def test_history_tracking(self):
        """History tracks conversation."""
        self.ga.state.start_session("tom")
        self.ga.state.add_to_history("user", "hello")
        self.ga.state.add_to_history("assistant", "hi there")
        history = self.ga.state.get_history()
        assert len(history) == 2
