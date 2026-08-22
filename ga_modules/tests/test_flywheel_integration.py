"""Integration test: coordinator + data flywheel."""
import os
import tempfile
from pathlib import Path
from ga_modules.core.coordinator import Coordinator, Response
from ga_modules.core.state_manager import StateManager
from ga_modules.core import EventBus
from ga_modules.core.ha_bridge import SafetyLayer


class TestCoordinatorFlywheel:
    def setup_method(self):
        self.bus = EventBus()
        self.state = StateManager("test-device", self.bus)
        self.coord = Coordinator("test-device", "gtv", self.bus, self.state)
        self.coord.set_safety_layer(SafetyLayer())
        
        # Override DB path for testing
        self.tmpdir = tempfile.mkdtemp()
        test_db = Path(self.tmpdir) / "test.db"
        self.coord.interaction_logger.db_path = test_db
        self.coord.interaction_logger._init_db()
        self.coord.cost_tracker.db_path = test_db
    
    def test_log_interaction(self):
        """Coordinator logs interactions."""
        self.state.start_session("tom")
        response = self.coord.route_command("turn off the server")
        
        assert response.source == "safety"
        stats = self.coord.interaction_logger.get_stats()
        assert stats["total_interactions"] == 1
    
    def test_multiple_routes(self):
        """Coordinator logs multiple interactions."""
        self.state.start_session("tom")
        
        for cmd in ["turn off the server", "play music", "what's the weather"]:
            self.coord.route_command(cmd)
        
        stats = self.coord.interaction_logger.get_stats()
        assert stats["total_interactions"] == 3
    
    def test_cost_tracking(self):
        """Cost tracker uses real token counts."""
        self.state.start_session("tom")
        
        for _ in range(10):
            self.coord.route_command("turn off the server")  # safety = local, 0 tokens
        
        cost = self.coord.cost_tracker.get_cost_summary()
        assert cost["total_interactions"] == 10
        # All safety (free/local) interactions -> 0 cloud tokens, 0 cost
        assert cost["total_tokens"] == 0
        assert cost["local_tokens"] == 0
        assert cost["cloud_tokens"] == 0
        assert cost["cloud_cost_usd"] == 0.0
    
    def test_get_flywheel_stats(self):
        """Coordinator exposes flywheel stats."""
        self.state.start_session("tom")
        self.coord.route_command("test")
        
        stats = self.coord.get_flywheel_stats()
        assert "interactions" in stats
        assert "cost" in stats
        assert "routes" in stats
        assert stats["interactions"]["total_interactions"] == 1
