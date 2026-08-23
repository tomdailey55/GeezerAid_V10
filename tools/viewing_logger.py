#!/usr/bin/env python3
"""
viewing_logger.py — passive viewing-history collector for GA-V9 Jeeves.

Polls all Cast-enabled devices on the LAN (Andrea's TCL Google TV, any
Chromecast) every few minutes and logs what's playing to SQLite:

    viewing_history.db
      └─ viewing_events(device, app_id, app_name, title, artist,
                        player_state, ts, duration_minutes)

This is the DATA SOURCE for the recommendation feedback loop:
  viewing_logger.py (cron, every 3 min) → viewing_history.db
        → taste_learner.py (nightly) → viewing_affinity.json
        → suggestion_engine.py (re-rank candidates by affinity)

Honest limits (by design):
  - Cast-status only reports TITLES for cast sessions (YouTube, Plex, etc.)
  - Native-app playback (Netflix launched on the TV itself) reports the
    APP but not the title (no cast session) — still useful service-level data
  - DRM content is never captured (no screencap here at all)

Usage:
    python3 viewing_logger.py            # one poll cycle, appends to DB
    python3 viewing_logger.py --once     # same
    python3 viewing_logger.py --report   # show recent history
"""
import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, "/Users/tomdailey/Public/GA-V9/tools")
sys.path.insert(0, "/Users/tomdailey/.venvs/jeeves-voice/lib/python3.12/site-packages")

import pychromecast  # noqa: E402

DB_PATH = Path.home() / "elder_brain" / "viewing_history.db"
POLL_INTERVAL = 3 * 60  # seconds between polls (cron drives this, not the script)

# --- Privacy / title-capture config ------------------------------------------
# Title capture is LOCAL-ONLY and fail-closed: we read the playing app + media
# title from Andrea's opted-in TV via ADB `dumpsys media_session` (the system
# media session) — NO screen capture, so DRM content is never an issue and no
# image ever leaves this MBP. We deliberately do NOT screencap or call a VLM
# for titles (a VLM hallucinated wrong app names from DRM-black frames; the
# media session is the accurate, non-DRM source). Nothing leaves the MBP.
# Disable entirely by setting GA_TV_TITLE_CAPTURE=0.
ADB = "/opt/homebrew/bin/adb"
ANDREA_TV_IP = "192.168.12.152"
# Only capture titles for these owners (Andrea opted in; tom is default-local too).
TITLE_CAPTURE_OWNERS = {"andrea"}
# Re-capture a title at most once per N seconds per device (avoid spamming ADB).
TITLE_CAPTURE_COOLDOWN_S = 15 * 60
TITLE_CAPTURE_ENABLED = os.getenv("GA_TV_TITLE_CAPTURE", "1") == "1"

# Device name -> owner. Andrea's TV (Master Bedroom TV) is HER viewing;
# everything else defaults to the household (tom).
OWNER_MAP = {
    "master bedroom tv": "andrea",
    "theater": "tom",
}
DEFAULT_OWNER = "tom"

# Holds {device: last_title_capture_ts} to enforce the cooldown in-process.
_last_title_capture: dict[str, float] = {}


def _owner_for(device_name: str) -> str:
    low = (device_name or "").lower()
    for frag, owner in OWNER_MAP.items():
        if frag in low:
            return owner
    return DEFAULT_OWNER


def _adb_connected() -> bool:
    """Ensure ADB to Andrea's TV is connected; reconnect if dropped."""
    try:
        out = subprocess.run(
            [ADB, "-s", f"{ANDREA_TV_IP}:5555", "get-state"],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip() == "device":
            return True
        # Offline/disconnected — reconnect.
        subprocess.run(
            [ADB, "connect", f"{ANDREA_TV_IP}:5555"],
            capture_output=True, text=True, timeout=15,
        )
        out2 = subprocess.run(
            [ADB, "-s", f"{ANDREA_TV_IP}:5555", "get-state"],
            capture_output=True, text=True, timeout=10,
        )
        return out2.returncode == 0 and out2.stdout.strip() == "device"
    except Exception:
        return False


def _capture_title_local(device_name: str) -> str:
    """Read what's on Andrea's TV from the Android media session via ADB.

    Uses `dumpsys media_session` + `dumpsys activity`, which report the
    playing app and media title straight from the system — NO screen capture.
    This avoids the DRM-black-frame + VLM-hallucination failure mode entirely
    (PBS/Netflix playback is DRM-protected, so screencap returns black and a
    VLM confabulates plausible-but-wrong titles). Returns a short title, or ''
    on any failure (fail-closed; nothing leaves this MBP).

    KNOWN LIMITATION: some apps (e.g. PBS) publish only an episode number in
    the media-session `description` and leave title/artist null, so the show
    name is not always available. We log what the system gives us and never
    fabricate a show title.

    NOTE: this is a deliberate replacement for the earlier screen-VLM approach.
    We do NOT use tv_adb.describe_screen (cloud fallback) and do NOT screencap.
    """
    if not TITLE_CAPTURE_ENABLED:
        return ""
    if not _adb_connected():
        print(f"[viewing] ADB to {ANDREA_TV_IP} not connected; skipping title capture")
        return ""
    # Cooldown: the media session is cheap, but don't spam it every poll.
    now = time.time()
    if now - _last_title_capture.get(device_name, 0) < TITLE_CAPTURE_COOLDOWN_S:
        return ""
    try:
        # 1. Which app is actually resumed (the truth about what's on screen).
        act = subprocess.run(
            [ADB, "-s", f"{ANDREA_TV_IP}:5555", "shell",
             "dumpsys activity activities | grep -i mResumedActivity"],
            capture_output=True, text=True, timeout=20,
        )
        pkg = ""
        m = re.search(r"com\.[a-z0-9.]+", act.stdout or "")
        if m:
            pkg = m.group(0)
        # 2. Media-session metadata (title) for that package.
        med = subprocess.run(
            [ADB, "-s", f"{ANDREA_TV_IP}:5555", "shell", "dumpsys media_session"],
            capture_output=True, text=True, timeout=20,
        )
        # Find the block belonging to pkg and pull its description/metadata title.
        title = ""
        if pkg:
            blocks = (med.stdout or "").split("Sessions:")
            for blk in blocks:
                if pkg in blk:
                    dm = re.search(r"description=([^,\n]+)", blk)
                    if dm and dm.group(1).strip() and dm.group(1) != "null":
                        title = dm.group(1).strip()
                        break
        if not title:
            return ""  # no media-session title available (menu/idle); don't fabricate
        # Some apps (e.g. PBS live) publish only an episode number with no show
        # name ("Episode 6"). That is noise, not a title — don't store it.
        if re.match(r"^Episode\s+\d+$", title, re.IGNORECASE):
            return ""
        _last_title_capture[device_name] = now
        return title
    except Exception as e:
        print(f"[viewing] title-capture skipped for {device_name}: {e}")
        return ""


def _connect_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS viewing_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,              -- ISO timestamp (local)
            device TEXT NOT NULL,
            owner TEXT DEFAULT 'tom',      -- who owns this viewing
            app_id TEXT,
            app_name TEXT,
            title TEXT,
            artist TEXT,
            player_state TEXT,             -- PLAYING / PAUSED / IDLE / UNKNOWN
            duration_minutes INTEGER DEFAULT 0
        )
    """)
    # Auto-migrate pre-owner databases (created before the per-user split)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(viewing_events)")]
    if "owner" not in cols:
        conn.execute("ALTER TABLE viewing_events ADD COLUMN owner TEXT DEFAULT 'tom'")
        print("[viewing] migrated DB: added owner column")
    conn.commit()
    return conn


def _discover_devices():
    """Return list of (device, cast) pairs. Best-effort; empty on failure."""
    out = []
    try:
        casts, browser = pychromecast.get_chromecasts(timeout=8)
        for c in casts:
            try:
                c.wait(timeout=6)
                out.append((c, c.name))
            except Exception:
                pass
        try:
            browser.stop_discovery()
        except Exception:
            pass
    except Exception as e:
        print(f"[viewing] discovery error: {e}")
    return out


def poll_once(conn) -> list:
    """Poll all devices once, insert rows. Returns the rows inserted."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for cast, name in _discover_devices():
        try:
            st = cast.media_controller.status
            title = getattr(st, "media_title", None) or ""
            artist = getattr(st, "media_artist", None) or ""
            state = getattr(st, "player_state", "UNKNOWN") or "UNKNOWN"
            app_id = cast.app_id or ""
            app_name = cast.app_display_name or ""
            # Idle devices: log the app-level state only (no title)
            if not title and not app_name and state == "UNKNOWN":
                continue  # fully idle — skip to keep DB clean
            owner = _owner_for(name)
            # Title capture: if we know the app but Cast gave no title, and this
            # owner has opted in, read it from the screen via ADB + LOCAL VLM.
            if owner in TITLE_CAPTURE_OWNERS and not title:
                captured = _capture_title_local(name)
                if captured:
                    title = captured
                    print(f"[viewing] title captured for {name}: {title!r}")
            rows.append((now, name, owner, app_id, app_name, title, artist, state, 0))
            print(f"[viewing] {name} ({owner}): app={app_name or '-'} title={title or '-'} state={state}")
        except Exception as e:
            print(f"[viewing] poll error for {name}: {e}")
    if rows:
        conn.executemany(
            "INSERT INTO viewing_events (ts, device, owner, app_id, app_name, title, artist, player_state, duration_minutes) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            rows,
        )
        conn.commit()
    return rows


def _aggregate_durations(conn) -> int:
    """Compute duration_minutes from consecutive same-app polling runs.

    Groups consecutive rows (ordered by ts) that share (device, owner, app_name)
    with no gap larger than ~3x the poll interval, and backfills duration_minutes
    = minutes from the group's first ts to its last ts. Returns rows updated.
    """
    from collections import defaultdict
    cur = conn.execute(
        "SELECT id, device, owner, app_name, ts FROM viewing_events "
        "ORDER BY device, owner, app_name, ts"
    )
    by_key: dict = defaultdict(list)
    for rid, device, owner, app_name, ts in cur.fetchall():
        by_key[(device, owner, app_name)].append((rid, ts))

    def _parse(s):
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")

    gap_tol = timedelta(seconds=POLL_INTERVAL * 3)
    updates = 0
    for (device, owner, app_name), items in by_key.items():
        items.sort(key=lambda x: x[1])
        # Break into runs where consecutive ts gap <= gap_tol.
        runs = []
        run = [items[0]]
        for it in items[1:]:
            if _parse(it[1]) - _parse(run[-1][1]) <= gap_tol:
                run.append(it)
            else:
                runs.append(run)
                run = [it]
        runs.append(run)
        for group in runs:
            if len(group) < 2:
                continue
            dur = max(1, round((_parse(group[-1][1]) - _parse(group[0][1])).total_seconds() / 60))
            ids = [rid for rid, _ in group]
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"UPDATE viewing_events SET duration_minutes = ? WHERE id IN ({placeholders})",
                [dur] + ids,
            )
            updates += len(ids)
    conn.commit()
    return updates


def report(conn, limit: int = 20):
    """Print recent history."""
    cur = conn.execute(
        "SELECT ts, device, app_name, title, artist, player_state FROM viewing_events "
        "ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    for ts, device, app, title, artist, state in cur.fetchall():
        print(f"{ts} | {device} | {app or '-'} | {title or '-'} | {artist or '-'} | {state}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="show recent history")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--aggregate", action="store_true",
                    help="only recompute durations, skip polling")
    args = ap.parse_args()

    conn = _connect_db()
    if args.aggregate:
        n = _aggregate_durations(conn)
        print(f"[viewing] aggregated durations on {n} rows")
        return
    if args.report:
        report(conn, args.limit)
        return

    poll_once(conn)
    n = _aggregate_durations(conn)
    if n:
        print(f"[viewing] aggregated durations on {n} rows")


if __name__ == "__main__":
    main()
