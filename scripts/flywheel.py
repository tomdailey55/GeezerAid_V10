#!/usr/bin/env python3
"""
GeezerAid V10 — Data Flywheel runner.

Closes the flywheel loop:
  1. Export accumulated interactions to eval/fine-tuning datasets.
  2. Report real cost accounting (from logged token counts).
  3. When enough clean (uncorrected) examples accumulate, emit a
     fine-tune-ready dataset. Actual fine-tuning is left to the available
     backend (MLX on MBP / ROCm on Strix) — this script prepares the data
     and reports readiness rather than blindly launching a training run.

Usage:
  python3 scripts/flywheel.py export [--since HOURS] [--out DIR]
  python3 scripts/flywheel.py report
  python3 scripts/flywheel.py status          # dataset readiness + cost
"""
import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ga_modules.core.data_flywheel import (  # noqa: E402
    InteractionLogger, EvalDataset, CostTracker,
)

HOME = Path.home() / ".geeza"
DB = HOME / "interactions.db"
# Threshold: how many clean (uncorrected) examples before a fine-tune run is worth it
MIN_FINETUNE_EXAMPLES = 200
MIN_CORRECTIONS = 5


def _db_rows_since(conn, since):
    return conn.execute(
        "SELECT command, model_source, result_text, user, room, corrected, correction_text "
        "FROM interactions WHERE timestamp > ?", (since,)
    ).fetchall()


def cmd_export(args):
    since = time.time() - args.since * 3600
    out = Path(args.out or HOME / "datasets")
    out.mkdir(parents=True, exist_ok=True)

    logger = InteractionLogger(DB)
    eval_ds = EvalDataset(logger)

    jsonl = eval_ds.export_jsonl(str(out / "flywheel.jsonl"), since=since)
    alpaca = eval_ds.export_alpaca(str(out / "flywheel_alpaca.json"), since=since)
    # Chat-format (messages arrays) — the format the proven finetune_standard.py needs
    messages = eval_ds.export_messages(str(out / "flywheel_messages.jsonl"), since=since)

    # Also write corrections (gold training signal)
    corrections = eval_ds.get_corrections(since=since)
    corr_path = out / "corrections.jsonl"
    with open(corr_path, "w") as f:
        for c in corrections:
            f.write(json.dumps(c) + "\n")

    print(json.dumps({
        "jsonl": jsonl,
        "alpaca": alpaca,
        "messages": messages,
        "corrections": str(corr_path),
        "corrections_count": len(corrections),
    }, indent=2))


def cmd_stats(args):
    logger = InteractionLogger(DB)
    cost = CostTracker(DB)
    print(json.dumps({
        "interactions": logger.get_stats(),
        "cost": cost.get_cost_summary(),
    }, indent=2))


def cmd_status(args):
    """Report whether accumulated data is ready to drive a fine-tune."""
    with sqlite3.connect(DB) as conn:
        clean = conn.execute(
            "SELECT COUNT(*) FROM interactions WHERE corrected = 0 AND result_text != '' "
            "AND timestamp > ?", (time.time() - 7 * 86400,)
        ).fetchone()[0]
        corrections = conn.execute(
            "SELECT COUNT(*) FROM interactions WHERE corrected = 1 "
            "AND timestamp > ?", (time.time() - 7 * 86400,)
        ).fetchone()[0]

    ready = clean >= MIN_FINETUNE_EXAMPLES and corrections >= MIN_CORRECTIONS
    print(json.dumps({
        "clean_examples_last_7d": clean,
        "corrections_last_7d": corrections,
        "min_clean_required": MIN_FINETUNE_EXAMPLES,
        "min_corrections_required": MIN_CORRECTIONS,
        "finetune_ready": ready,
        "next_action": ("Run the fine-tune job now" if ready
                        else "Keep logging — need more clean examples and corrections"),
    }, indent=2))


def main():
    p = argparse.ArgumentParser(description="Data flywheel runner")
    sub = p.add_subparsers(dest="cmd", required=True)

    se = sub.add_parser("export", help="Export eval datasets")
    se.add_argument("--since", type=float, default=24.0, help="Hours back to export")
    se.add_argument("--out", default=None, help="Output directory")
    se.set_defaults(func=cmd_export)

    ss = sub.add_parser("stats", help="Cost + interaction stats")
    ss.set_defaults(func=cmd_stats)

    st = sub.add_parser("status", help="Fine-tune readiness")
    st.set_defaults(func=cmd_status)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
