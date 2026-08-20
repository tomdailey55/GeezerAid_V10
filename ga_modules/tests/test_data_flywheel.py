"""Tests for the data flywheel."""
import os
import sqlite3
import tempfile
import time
from ga_modules.core.data_flywheel import (
    InteractionLogger, EvalDataset, CostTracker, Interaction, patch_coordinator
)


class TestInteractionLogger:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db = os.path.join(self.tmpdir, "test.db")
        self.logger = InteractionLogger(self.db)

    def test_init_db(self):
        assert os.path.exists(self.db)

    def test_log_interaction(self):
        interaction = Interaction(
            command="turn on the lights",
            model_source="ha_intent",
            result_text="Done.",
            timestamp=time.time(),
            user="tom",
            room="kitchen"
        )
        self.logger.log(interaction)
        
        stats = self.logger.get_stats()
        assert stats["total_interactions"] == 1

    def test_mark_corrected(self):
        interaction = Interaction(
            command="play it",
            model_source="cloud_llm",
            result_text="Playing...",
            timestamp=time.time()
        )
        self.logger.log(interaction)
        self.logger.mark_corrected("play it", "play it on HBO")
        
        stats = self.logger.get_stats()
        assert stats["corrections"] == 1


class TestEvalDataset:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db = os.path.join(self.tmpdir, "test.db")
        self.logger = InteractionLogger(self.db)
        self.eval = EvalDataset(self.logger)
        
        # Add some test data
        for i in range(5):
            self.logger.log(Interaction(
                command=f"test command {i}",
                model_source="ha_intent",
                result_text=f"result {i}",
                timestamp=time.time()
            ))

    def test_export_jsonl(self):
        path = self.eval.export_jsonl(os.path.join(self.tmpdir, "test.jsonl"))
        assert os.path.exists(path)
        
        with open(path) as f:
            lines = f.readlines()
        assert len(lines) == 5

    def test_export_alpaca(self):
        path = self.eval.export_alpaca(os.path.join(self.tmpdir, "test.json"))
        assert os.path.exists(path)
        
        import json
        with open(path) as f:
            data = json.load(f)
        assert len(data) == 5
        assert "instruction" in data[0]


class TestCostTracker:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db = os.path.join(self.tmpdir, "test.db")
        self.logger = InteractionLogger(self.db)
        self.cost = CostTracker(self.db)
        
        # Add interactions
        for _ in range(10):
            self.logger.log(Interaction(
                command="local",
                model_source="local_llm",
                result_text="ok",
                timestamp=time.time()
            ))
        for _ in range(5):
            self.logger.log(Interaction(
                command="cloud",
                model_source="cloud_llm",
                result_text="ok",
                timestamp=time.time()
            ))

    def test_cost_summary(self):
        summary = self.cost.get_cost_summary()
        assert summary["total_interactions"] == 15
        assert summary["by_source"]["local_llm"] == 10
        assert summary["by_source"]["cloud_llm"] == 5
        assert summary["savings_usd"] > 0
