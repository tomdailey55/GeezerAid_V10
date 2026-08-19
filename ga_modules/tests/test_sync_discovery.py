"""
Tests for the Sync Engine and Discovery.
"""
import pytest
import time
from ga_modules.core import EventBus
from ga_modules.core.sync_engine import (
    CRDTStore, SyncEngine, Operation, VectorClock
)
from ga_modules.core.discovery import DeviceDiscovery


class TestVectorClock:
    def test_increment(self):
        vc = VectorClock()
        vc.increment("device_a")
        vc.increment("device_a")
        assert vc.clocks["device_a"] == 2

    def test_merge(self):
        vc1 = VectorClock({"a": 1, "b": 2})
        vc2 = VectorClock({"b": 3, "c": 1})
        vc1.merge(vc2)
        assert vc1.clocks == {"a": 1, "b": 3, "c": 1}

    def test_happens_before(self):
        vc1 = VectorClock({"a": 1, "b": 2})
        vc2 = VectorClock({"a": 2, "b": 3})
        assert vc1.happens_before(vc2) is True
        assert vc2.happens_before(vc1) is False

    def test_copy(self):
        vc = VectorClock({"a": 1})
        vc2 = vc.copy()
        vc2.increment("a")
        assert vc.clocks["a"] == 1
        assert vc2.clocks["a"] == 2


class TestCRDTStore:
    def test_apply_and_get(self):
        store = CRDTStore()
        store.apply(Operation("key1", "value1", "dev_a", time.time()))
        assert store.get("key1") == "value1"

    def test_last_writer_wins(self):
        store = CRDTStore()
        store.apply(Operation("key1", "old", "dev_a", 1000.0))
        store.apply(Operation("key1", "new", "dev_b", 2000.0))
        assert store.get("key1") == "new"

    def test_get_all(self):
        store = CRDTStore()
        store.apply(Operation("k1", "v1", "dev_a", time.time()))
        store.apply(Operation("k2", "v2", "dev_b", time.time()))
        all_state = store.get_all()
        assert all_state == {"k1": "v1", "k2": "v2"}

    def test_since(self):
        store = CRDTStore()
        op1 = Operation("k1", "v1", "dev_a", time.time(), device_clock=1)
        op2 = Operation("k2", "v2", "dev_a", time.time(), device_clock=2)
        store.apply(op1)
        store.apply(op2)
        
        vc = VectorClock({"dev_a": 1})
        recent = store.since(vc)
        assert len(recent) == 1
        assert recent[0].key == "k2"

    def test_merge(self):
        store1 = CRDTStore()
        store1.apply(Operation("k1", "v1", "dev_a", time.time()))
        
        store2 = CRDTStore()
        store2.apply(Operation("k2", "v2", "dev_b", time.time()))
        
        store1.merge(store2)
        assert store1.get("k1") == "v1"
        assert store1.get("k2") == "v2"


class TestSyncEngine:
    def setup_method(self):
        self.bus = EventBus()
        self.sync = SyncEngine("test-device", self.bus)

    def test_set_and_get(self):
        self.sync.set("key", "value")
        assert self.sync.get("key") == "value"

    def test_get_all(self):
        self.sync.set("k1", "v1")
        self.sync.set("k2", "v2")
        all_state = self.sync.get_all()
        assert all_state == {"k1": "v1", "k2": "v2"}

    def test_add_peer(self):
        self.sync.add_peer("other-device")
        assert "other-device" in self.sync.peers

    def test_remove_peer(self):
        self.sync.add_peer("other-device")
        self.sync.remove_peer("other-device")
        assert "other-device" not in self.sync.peers

    def test_household_change_triggers_set(self):
        """Household change event triggers sync set."""
        self.bus.publish("ga.household.change", {"key": "test_key", "value": "test_value"})
        assert self.sync.get("test_key") == "test_value"


class TestDiscovery:
    def setup_method(self):
        self.bus = EventBus()
        self.discovery = DeviceDiscovery("test-device", self.bus)

    def test_add_device(self):
        self.discovery.add_device("other", "192.168.1.100", 8766)
        assert "other" in self.discovery.devices

    def test_resolve(self):
        self.discovery.add_device("other", "192.168.1.100", 8766)
        url = self.discovery.resolve("other")
        assert url == "http://192.168.1.100:8766"

    def test_resolve_missing(self):
        assert self.discovery.resolve("missing") is None

    def test_discover(self):
        self.discovery.add_device("other", "192.168.1.100", 8766, ["stt", "tts"])
        devices = self.discovery.discover()
        assert len(devices) == 1
        assert devices[0]["device_id"] == "other"

    def test_remove_device(self):
        self.discovery.add_device("other", "192.168.1.100", 8766)
        self.discovery.remove_device("other")
        assert "other" not in self.discovery.devices
