"""
Tests for the Event Bus.
"""
import pytest
import time
from ga_modules.core import EventBus, get_event_bus


class TestEventBus:
    def setup_method(self):
        self.bus = EventBus()  # fresh bus per test, not singleton
        self.received = []

    def test_publish_subscribe(self):
        """Basic pub/sub works."""
        self.bus.subscribe("ga.wake.detected", lambda msg: self.received.append(msg))
        self.bus.publish("ga.wake.detected", {"device_id": "kitchen", "user": "tom"})
        
        assert len(self.received) == 1
        assert self.received[0]["topic"] == "ga.wake.detected"
        assert self.received[0]["payload"]["user"] == "tom"

    def test_wildcard_single_level(self):
        """* matches one level."""
        self.bus.subscribe("ga.wake.*", lambda msg: self.received.append(msg))
        
        self.bus.publish("ga.wake.detected", {})
        self.bus.publish("ga.wake.missed", {})
        self.bus.publish("ga.command.received", {})  # should NOT match
        
        assert len(self.received) == 2

    def test_wildcard_multi_level(self):
        """# matches zero or more levels."""
        self.bus.subscribe("ga.#", lambda msg: self.received.append(msg))
        
        self.bus.publish("ga.wake.detected", {})
        self.bus.publish("ga.command.received", {})
        self.bus.publish("other.topic", {})  # should NOT match
        
        assert len(self.received) == 2

    def test_multiple_subscribers(self):
        """Multiple handlers on same topic."""
        results_a = []
        results_b = []
        
        self.bus.subscribe("ga.test", lambda msg: results_a.append(msg))
        self.bus.subscribe("ga.test", lambda msg: results_b.append(msg))
        self.bus.publish("ga.test", {"data": 1})
        
        assert len(results_a) == 1
        assert len(results_b) == 1

    def test_unsubscribe(self):
        """Unsubscribe removes handler."""
        handler = lambda msg: self.received.append(msg)
        
        self.bus.subscribe("ga.test", handler)
        self.bus.publish("ga.test", {})
        self.bus.unsubscribe("ga.test", handler)
        self.bus.publish("ga.test", {})
        
        assert len(self.received) == 1

    def test_recent_messages(self):
        """Recent message log works."""
        for i in range(5):
            self.bus.publish("ga.test", {"n": i})
        
        recent = self.bus.recent(3)
        assert len(recent) == 3
        assert recent[-1]["payload"]["n"] == 4

    def test_handler_error_isolation(self):
        """One handler error doesn't break others."""
        def bad_handler(msg):
            raise RuntimeError("oops")
        
        self.bus.subscribe("ga.test", bad_handler)
        self.bus.subscribe("ga.test", lambda msg: self.received.append(msg))
        
        # Should not raise
        self.bus.publish("ga.test", {})
        assert len(self.received) == 1

    def test_payload_isolation(self):
        """Published payload can't be mutated by handler."""
        payload = {"data": [1, 2, 3]}
        
        def mutate(msg):
            msg["payload"]["data"].append(4)
        
        self.bus.subscribe("ga.test", mutate)
        self.bus.publish("ga.test", payload)
        
        # Original payload should be intact
        assert payload["data"] == [1, 2, 3]


class TestTopicMatching:
    def setup_method(self):
        self.bus = EventBus()

    def test_exact_match(self):
        assert self.bus._topic_matches("ga.wake.detected", "ga.wake.detected")

    def test_star_single(self):
        assert self.bus._topic_matches("ga.wake.*", "ga.wake.detected")
        assert not self.bus._topic_matches("ga.wake.*", "ga.wake.missed.extra")

    def test_hash_multi(self):
        assert self.bus._topic_matches("ga.#", "ga.wake.detected")
        assert self.bus._topic_matches("ga.#", "ga.wake.detected.foo.bar")
        assert not self.bus._topic_matches("ga.#", "other.topic")

    def test_complex_pattern(self):
        assert self.bus._topic_matches("ga.*.detected", "ga.wake.detected")
        assert self.bus._topic_matches("ga.*.detected", "ga.motion.detected")
        assert not self.bus._topic_matches("ga.*.detected", "ga.wake.missed")


class TestSingleton:
    def test_singleton(self):
        bus1 = get_event_bus()
        bus2 = get_event_bus()
        assert bus1 is bus2
