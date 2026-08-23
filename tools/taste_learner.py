#!/usr/bin/env python3
"""
taste_learner.py — turn viewing history into taste signals for GA-V9.

Nightly aggregation of viewing_history.db → viewing_affinity.json.

The suggestion engine reads viewing_affinity.json and re-ranks candidates:
titles/genres/artists the household actually watches get a boost.

Output schema (viewing_affinity.json):
{
  "generated_at": "2026-08-04T22:00:00",
  "totals": {"events": N, "hours_watched": H},
  "app_affinity": {"YouTube": 5, "Netflix": 3},        // by event count
  "title_affinity": {"The Crown": 3, "Blade Runner": 2},
  "artist_affinity": {"Hans Zimmer": 2},               // from cast media
  "recent_titles": ["...", ...]                         // last 30 days, newest first
}
"""
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path.home() / "elder_brain" / "viewing_history.db"
OUT_DIR = Path.home() / "elder_brain"
LOOKBACK_DAYS = 60
OWNERS = ["tom", "andrea"]  # per-owner affinity files


def load_events(days: int = LOOKBACK_DAYS) -> list:
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(str(DB_PATH))
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute(
        "SELECT ts, device, owner, app_name, title, artist, player_state "
        "FROM viewing_events WHERE ts >= ?",
        (since,),
    )
    rows = [dict(zip(["ts", "device", "owner", "app_name", "title", "artist", "state"], r))
            for r in cur.fetchall()]
    conn.close()
    return rows


def _clean(s: str) -> str:
    """Strip common noise so 'The Crown' and 'the crown' count once."""
    s = (s or "").strip()
    if not s or s.lower() in ("unknown", "none", "n/a"):
        return ""
    return s


def build_affinity(events: list) -> dict:
    apps = Counter()
    titles = Counter()
    artists = Counter()
    hours = 0.0

    for e in events:
        app = _clean(e.get("app_name"))
        title = _clean(e.get("title"))
        artist = _clean(e.get("artist"))
        if app:
            apps[app] += 1
        if title and e.get("state") == "PLAYING":
            titles[title] += 1
        if artist and e.get("state") == "PLAYING":
            artists[artist] += 1
        # Duration is unknown per poll; assume each logged playing event ~3 min
        # (the poll interval). Good enough for relative weighting.
        if e.get("state") == "PLAYING":
            hours += POLL_INTERVAL_MINUTES / 60.0

    recent = [e["title"] for e in reversed(events) if _clean(e.get("title"))][:20]

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "totals": {"events": len(events), "hours_watched": round(hours, 1)},
        "app_affinity": dict(apps.most_common(10)),
        "title_affinity": dict(titles.most_common(15)),
        "artist_affinity": dict(artists.most_common(10)),
        "recent_titles": recent,
    }


POLL_INTERVAL_MINUTES = 3  # matches viewing_logger POLL_INTERVAL


def _write_empty(owner: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"viewing_affinity_{owner}.json"
    out.write_text(json.dumps({
        "owner": owner,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "totals": {"events": 0, "hours_watched": 0},
        "app_affinity": {},
        "title_affinity": {},
        "artist_affinity": {},
        "recent_titles": [],
    }, indent=2))


def main():
    events = load_events()
    # Always write a file per owner so the engine can distinguish
    # "no data yet" from "error" regardless of collection state.
    for owner in OWNERS:
        own = [e for e in events if e.get("owner") == owner]
        if not own:
            _write_empty(owner)
            print(f"[taste_learner] {owner}: no events — empty affinity written")
            continue
        affinity = build_affinity(own)
        affinity["owner"] = owner
        out = OUT_DIR / f"viewing_affinity_{owner}.json"
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(affinity, indent=2))
        print(f"[taste_learner] {owner}: {len(own)} events, "
              f"{affinity['totals']['hours_watched']}h watched → {out.name}")


if __name__ == "__main__":
    main()
