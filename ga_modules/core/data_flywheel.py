"""
GeezerAid V10 — Data Flywheel

The observation layer. Logs every interaction, routes to the best model,
tracks cost, and builds eval datasets from real household usage.

Inspired by NVIDIA Switchyard:
  - Instrument: log production traffic
  - Build eval: fine-tuning datasets from logs
  - Evaluate: smaller models, promote what works
  - Cost: don't spend frontier money on tasks Quinn can do

Flywheel loop:
  1. User speaks → coordinator routes to model
  2. InteractionLogger records: command, model, result, timestamp, correction
  3. EvalDataset exports accumulated logs as training data
  4. CostTracker shows cloud spend vs local savings
"""

import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

logger = logging.getLogger(__name__)


@dataclass
class Interaction:
    """A single GA interaction."""
    command: str
    model_source: str      # "ha_intent", "knowledge", "local_llm", "cloud_llm", "safety"
    result_text: str
    timestamp: float
    user: str = "unknown"
    room: str = "unknown"
    corrected: bool = False    # True if user rephrased/corrected
    correction_text: str = ""  # What they said instead
    latency_ms: float = 0.0
    prompt_tokens: int = 0    # Real usage from LLM (0 if local/free or unknown)
    completion_tokens: int = 0
    model: str = ""            # Model id actually used (e.g. "local/qwen3.5", "cloud/longcat")
    
    def to_dict(self) -> dict:
        return asdict(self)


class InteractionLogger:
    """Logs every interaction to SQLite for the flywheel."""
    
    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        if db_path is None:
            db_path = Path.home() / ".geeza" / "interactions.db"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """Initialize the SQLite database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS interactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    command TEXT NOT NULL,
                    model_source TEXT NOT NULL,
                    result_text TEXT,
                    timestamp REAL NOT NULL,
                    user TEXT DEFAULT 'unknown',
                    room TEXT DEFAULT 'unknown',
                    corrected INTEGER DEFAULT 0,
                    correction_text TEXT DEFAULT '',
                    latency_ms REAL DEFAULT 0.0,
                    prompt_tokens INTEGER DEFAULT 0,
                    completion_tokens INTEGER DEFAULT 0,
                    model TEXT DEFAULT ''
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_interactions_timestamp 
                ON interactions(timestamp)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_interactions_source 
                ON interactions(model_source)
            """)
            conn.commit()
            # Migrate existing DBs (add token/model columns if missing)
            for ddl in [
                "ALTER TABLE interactions ADD COLUMN prompt_tokens INTEGER DEFAULT 0",
                "ALTER TABLE interactions ADD COLUMN completion_tokens INTEGER DEFAULT 0",
                "ALTER TABLE interactions ADD COLUMN model TEXT DEFAULT ''",
            ]:
                try:
                    conn.execute(ddl)
                except sqlite3.OperationalError:
                    pass  # column already exists
            conn.commit()
    
    def log(self, interaction: Interaction):
        """Log a single interaction."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO interactions 
                (command, model_source, result_text, timestamp, user, room, corrected, correction_text, latency_ms, prompt_tokens, completion_tokens, model)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                interaction.command,
                interaction.model_source,
                interaction.result_text,
                interaction.timestamp,
                interaction.user,
                interaction.room,
                1 if interaction.corrected else 0,
                interaction.correction_text,
                interaction.latency_ms,
                interaction.prompt_tokens,
                interaction.completion_tokens,
                interaction.model
            ))
            conn.commit()
        logger.debug(f"Logged interaction: {interaction.command[:50]}... → {interaction.model_source}")
    
    def mark_corrected(self, command: str, correction: str):
        """Mark a command as corrected by the user."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE interactions 
                SET corrected = 1, correction_text = ?
                WHERE command = ? AND timestamp > ?
            """, (correction, command, time.time() - 300))  # last 5 min
            conn.commit()
    
    def get_stats(self) -> dict:
        """Get interaction statistics."""
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM interactions").fetchone()[0]
            sources = {}
            for row in conn.execute("SELECT model_source, COUNT(*) FROM interactions GROUP BY model_source"):
                sources[row[0]] = row[1]
            corrections = conn.execute("SELECT COUNT(*) FROM interactions WHERE corrected = 1").fetchone()[0]
            recent = conn.execute(
                "SELECT command, model_source, timestamp FROM interactions ORDER BY timestamp DESC LIMIT 5"
            ).fetchall()
        
        return {
            "total_interactions": total,
            "by_source": sources,
            "corrections": corrections,
            "recent": [{"command": r[0][:50], "source": r[1], "time": datetime.fromtimestamp(r[2]).strftime("%H:%M")} for r in recent]
        }


class EvalDataset:
    """Generate eval/fine-tuning datasets from accumulated interactions."""
    
    def __init__(self, interaction_logger: InteractionLogger):
        self.logger = interaction_logger
    
    def export_jsonl(self, output_path: Optional[str] = None, since: float = 0) -> str:
        """Export interactions as JSONL for fine-tuning."""
        if output_path is None:
            output_path = Path.home() / ".geeza" / "eval_dataset.jsonl"
        output_path = Path(output_path)
        
        with sqlite3.connect(self.logger.db_path) as conn:
            rows = conn.execute("""
                SELECT command, model_source, result_text, user, room, corrected, correction_text
                FROM interactions
                WHERE timestamp > ?
                ORDER BY timestamp
            """, (since,)).fetchall()
        
        count = 0
        with open(output_path, 'w') as f:
            for row in rows:
                command, source, result, user, room, corrected, correction = row
                
                # Build training example
                example = {
                    "input": command,
                    "output": result,
                    "metadata": {
                        "source": source,
                        "user": user,
                        "room": room,
                        "corrected": bool(corrected),
                        "correction": correction if corrected else None
                    }
                }
                f.write(json.dumps(example) + "\n")
                count += 1
        
        logger.info(f"Exported {count} interactions to {output_path}")
        return str(output_path)
    
    def export_alpaca(self, output_path: Optional[str] = None, since: float = 0) -> str:
        """Export in Alpaca format for fine-tuning."""
        if output_path is None:
            output_path = Path.home() / ".geeza" / "eval_alpaca.json"
        output_path = Path(output_path)
        
        with sqlite3.connect(self.logger.db_path) as conn:
            rows = conn.execute("""
                SELECT command, result_text, user, room
                FROM interactions
                WHERE timestamp > ? AND corrected = 0
                ORDER BY timestamp
            """, (since,)).fetchall()
        
        examples = []
        for row in rows:
            command, result, user, room = row
            examples.append({
                "instruction": command,
                "input": f"User: {user}, Room: {room}",
                "output": result
            })
        
        with open(output_path, 'w') as f:
            json.dump(examples, f, indent=2)
        
        logger.info(f"Exported {len(examples)} Alpaca examples to {output_path}")
        return str(output_path)
    
    def get_corrections(self, since: float = 0) -> list:
        """Get all corrections (user rephrased/corrected) — gold for fine-tuning."""
        with sqlite3.connect(self.logger.db_path) as conn:
            rows = conn.execute("""
                SELECT command, correction_text, model_source
                FROM interactions
                WHERE corrected = 1 AND timestamp > ?
                ORDER BY timestamp DESC
            """, (since,)).fetchall()
        
        return [{"original": r[0], "correction": r[1], "source": r[2]} for r in rows]


class CostTracker:
    """Track cloud vs local routing costs using REAL token counts."""

    # Cost per 1M tokens (USD) by model id. Keys match the `model` column we
    # log; anything unknown defaults to cloud. Local/free models cost 0.
    MODEL_COST_PER_1M = {
        # Local — free
        "": 0.0,                 # unknown / non-LLM
        "local": 0.0,            # local llama.cpp
        "ha_intent": 0.0,
        "knowledge": 0.0,
        "safety": 0.0,
        # Cloud (Nous / OpenRouter class pricing)
        "cloud": 0.003,          # ~$3/1M blended fallback
        "longcat": 0.0025,
        "gpt-4o": 0.005,
        "claude-sonnet": 0.003,
        "deepseek-v4": 0.0005,
    }
    FALLBACK_COST_PER_1M = 0.003

    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        if db_path is None:
            db_path = Path.home() / ".geeza" / "interactions.db"
        self.db_path = Path(db_path)

    def get_cost_summary(self) -> dict:
        """Compute cost from logged token counts (not estimates)."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT model_source, prompt_tokens, completion_tokens, model FROM interactions"
            ).fetchall()

        total_tokens = 0
        cloud_tokens = 0
        local_tokens = 0
        cloud_cost = 0.0
        by_source = {}
        for source, pt, ct, model in rows:
            tokens = (pt or 0) + (ct or 0)
            total_tokens += tokens
            by_source[source] = by_source.get(source, 0) + 1
            # Cost key: use the model column if it names a priced model, else the source.
            key = model if model in self.MODEL_COST_PER_1M else source
            cost_per_1m = self.MODEL_COST_PER_1M.get(key, self.FALLBACK_COST_PER_1M)
            if cost_per_1m > 0:
                cloud_tokens += tokens
                cloud_cost += tokens / 1_000_000 * cost_per_1m
            else:
                local_tokens += tokens

        total_interactions = sum(by_source.values())
        # What it WOULD cost if every interaction were cloud at blended rate
        all_cloud_cost = total_tokens / 1_000_000 * self.FALLBACK_COST_PER_1M
        savings = all_cloud_cost - cloud_cost

        return {
            "total_interactions": total_interactions,
            "total_tokens": total_tokens,
            "by_source": by_source,
            "cloud_tokens": cloud_tokens,
            "local_tokens": local_tokens,
            "cloud_cost_usd": round(cloud_cost, 6),
            "all_cloud_cost_usd": round(all_cloud_cost, 6),
            "savings_usd": round(savings, 6),
            "savings_percent": round((savings / all_cloud_cost * 100) if all_cloud_cost > 0 else 0, 1)
        }


# ============================================================
# Integration: patch into coordinator
# ============================================================

def patch_coordinator(coordinator, db_path: Optional[str] = None):
    """Patch the coordinator with data flywheel capabilities."""
    
    interaction_logger = InteractionLogger(db_path)
    eval_dataset = EvalDataset(interaction_logger)
    cost_tracker = CostTracker(interaction_logger.db_path)
    
    # Store original route_command
    original_route = coordinator.route_command
    
    def route_and_log(command: str, context: dict = None):
        """Wrapped route_command that logs the interaction."""
        start_time = time.time()
        response = original_route(command, context)
        latency_ms = (time.time() - start_time) * 1000
        
        # Log the interaction
        interaction = Interaction(
            command=command,
            model_source=response.source if hasattr(response, 'source') else "unknown",
            result_text=response.text if hasattr(response, 'text') else str(response),
            timestamp=time.time(),
            user=context.get("user", "unknown") if context else "unknown",
            room=context.get("room", "unknown") if context else "unknown",
            latency_ms=latency_ms
        )
        interaction_logger.log(interaction)
        
        return response
    
    # Replace route_command
    coordinator.route_command = route_and_log
    
    # Add flywheel methods
    coordinator.interaction_logger = interaction_logger
    coordinator.eval_dataset = eval_dataset
    coordinator.cost_tracker = cost_tracker
    coordinator.get_flywheel_stats = lambda: {
        "interactions": interaction_logger.get_stats(),
        "cost": cost_tracker.get_cost_summary()
    }
    
    logger.info("Data flywheel patched into coordinator")
    return coordinator
