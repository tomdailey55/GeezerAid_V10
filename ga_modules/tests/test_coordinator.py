"""
Tests for the Coordinator and HA Bridge.
"""
import pytest
from ga_modules.core import EventBus
from ga_modules.core.state_manager import StateManager
from ga_modules.core.coordinator import Coordinator, Response
from ga_modules.core.ha_bridge import HABridge, Intent, Entity, SafetyLayer


class TestCoordinator:
    def setup_method(self):
        self.bus = EventBus()
        self.state = StateManager("gtv-kitchen", self.bus)
        self.coord = Coordinator("gtv-kitchen", "gtv", self.bus, self.state)

    def test_register_module(self):
        """Modules register."""
        self.coord.register_module("stt", object())
        assert "stt" in self.coord.modules

    def test_route_command_safety(self):
        """Safety check blocks dangerous commands."""
        safety = SafetyLayer()
        self.coord.set_safety_layer(safety)
        
        resp = self.coord.route_command("turn off the server")
        assert resp.source == "safety"

    def test_route_command_ha_intent(self):
        """HA intent fast path works."""
        ha = HABridge(event_bus=self.bus)
        self.coord.set_ha_bridge(ha)
        
        resp = self.coord.route_command("turn on the kitchen lights")
        assert resp.source == "ha_intent"

    def test_route_command_cloud_fallback(self):
        """Falls back to cloud when no local modules."""
        resp = self.coord.route_command("what's the meaning of life?")
        assert resp.source in ("cloud_llm", "error")

    def test_select_tts_voice(self):
        """Per-user voice selection."""
        assert self.coord.select_tts_voice("tom") == "en_US-libritts-high"
        assert self.coord.select_tts_voice("andrea") == "en_US-amy-medium"
        assert self.coord.select_tts_voice("unknown") == "en_US-libritts-high"

    def test_get_route_stats(self):
        """Route stats track."""
        self.coord.route_command("turn on the lights")
        stats = self.coord.get_route_stats()
        assert "ha_intent" in stats

    def test_route_voice_no_stt(self):
        """Voice routing without STT returns error."""
        resp = self.coord.route_voice(b"audio_data")
        assert resp.source == "error"


class TestHABridge:
    def setup_method(self):
        self.bus = EventBus()
        self.ha = HABridge(event_bus=self.bus)

    def test_match_intent_turn_on(self):
        """Turn on command matches."""
        intent = self.ha.match_intent("turn on the kitchen lights")
        assert intent is not None
        assert intent.service == "homeassistant.turn_on"
        assert "kitchen" in (intent.entity or "")

    def test_match_intent_turn_off(self):
        """Turn off command matches."""
        intent = self.ha.match_intent("turn off the bedroom lights")
        assert intent is not None
        assert intent.service == "homeassistant.turn_off"

    def test_match_intent_thermostat(self):
        """Thermostat command matches."""
        intent = self.ha.match_intent("set the thermostat to 72")
        assert intent is not None
        # "set X to Y" → homeassistant.set_value (generic)
        assert intent.service == "homeassistant.set_value"
        assert "thermostat" in (intent.entity or "")
        assert intent.value == "72"

    def test_match_intent_no_match(self):
        """Non-matching command returns None."""
        intent = self.ha.match_intent("what's the meaning of life?")
        assert intent is None

    def test_call_service(self):
        """Service call returns result."""
        result = self.ha.call_service("light.turn_on", "kitchen")
        assert result["success"] is True
        assert result["entity_id"] == "kitchen"

    def test_add_entity(self):
        """Entity registry works."""
        entity = Entity(
            entity_id="light.kitchen",
            domain="light",
            state="off",
            services=["turn_on", "turn_off"],
        )
        self.ha.add_entity(entity)
        assert "light.kitchen" in self.ha.entities

    def test_available_tools(self):
        """Available tools lists from entities."""
        self.ha.add_entity(Entity(
            entity_id="light.kitchen",
            domain="light",
            state="off",
            services=["turn_on", "turn_off"],
        ))
        tools = self.ha.available_tools()
        assert len(tools) == 2

    def test_can_control(self):
        """Can control check works."""
        self.ha.add_entity(Entity(
            entity_id="light.kitchen",
            domain="light",
            state="off",
        ))
        assert self.ha.can_control("turn on the kitchen") is True
        assert self.ha.can_control("what's the weather") is False


class TestSafetyLayer:
    def setup_method(self):
        self.safety = SafetyLayer()

    def test_dangerous_server(self):
        """Server power is dangerous."""
        assert self.safety.is_dangerous("turn off the server") is True

    def test_dangerous_water_heater(self):
        """Water heater is dangerous."""
        assert self.safety.is_dangerous("turn off the water heater") is True

    def test_safe_lights(self):
        """Lights are safe."""
        assert self.safety.is_dangerous("turn on the lights") is False

    def test_safe_weather(self):
        """Questions are safe."""
        assert self.safety.is_dangerous("what's the weather") is False


class TestResponse:
    def test_response_defaults(self):
        """Response defaults."""
        resp = Response("Hello there.")
        assert resp.text == "Hello there."
        assert resp.summary == "Hello there."
        assert resp.source == "unknown"

    def test_response_truncates_summary(self):
        """Summary truncates long text."""
        resp = Response("x" * 200)
        assert len(resp.summary) == 100

    def test_response_repr(self):
        """Repr is readable."""
        resp = Response("Test", source="ha_intent")
        assert "ha_intent" in repr(resp)


class TestIntegration:
    """Integration: coordinator + HA + safety + state."""

    def setup_method(self):
        self.bus = EventBus()
        self.state = StateManager("gtv-kitchen", self.bus)
        self.coord = Coordinator("gtv-kitchen", "gtv", self.bus, self.state)
        self.ha = HABridge(event_bus=self.bus)
        self.safety = SafetyLayer()
        self.coord.set_ha_bridge(self.ha)
        self.coord.set_safety_layer(self.safety)

    def test_full_flow_lights(self):
        """Full flow: turn on lights."""
        self.state.start_session("tom")
        resp = self.coord.route_command("turn on the kitchen lights")
        assert resp.source == "ha_intent"
        assert "Done" in resp.text

    def test_full_flow_safety_block(self):
        """Full flow: safety blocks server power."""
        self.state.start_session("tom")
        resp = self.coord.route_command("turn off the server")
        assert resp.source == "safety"

    def test_full_flow_context(self):
        """Context flows to coordinator."""
        self.state.start_session("tom")
        self.state.add_to_history("user", "turn on the lights")
        
        ctx = self.state.get_context()
        assert ctx["user"] == "tom"
        assert ctx["room"] == "kitchen"
        assert len(ctx["history"]) == 1

    def test_event_bus_integration(self):
        """Events flow through bus."""
        received = []
        self.bus.publish("ga.test", {"data": 1})
        
        # Message should be in log
        recent = self.bus.recent(1)
        assert len(recent) == 1
        assert recent[0]["topic"] == "ga.test"
