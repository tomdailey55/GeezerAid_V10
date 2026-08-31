#!/usr/bin/env python3
"""desk_data.py — GA-Desk card data provider (runs on Strix next to
gtv_chrome_server.py). Returns calendar + reminders + weather as one JSON
document for the /api/desk-data route.

Provenance is explicit: every section says whether it is LIVE (AppleScript
to the local user's Calendar/Reminders on Strix — currently nobody's
account, so usually empty) or SEED (demo data from ga_context.json).
No fabrication: a live-but-empty source returns [], not invented rows.
"""
import json
import os
import shutil
import subprocess
import time

CONTEXT_FILE = os.path.expanduser("~/Public/GA-V9/ga_context.json")
CONTEXT_FILE_ALT = os.path.expanduser("~/mbp-public/GA-V9/ga_context.json")
_CACHE = {"t": 0.0, "data": None}
CACHE_TTL = 60  # seconds; desk cards are not high-frequency data


def _has_osascript():
    return shutil.which("osascript") is not None

APPLESCRIPT = """
on run
  set out to ""
  tell application "Calendar" to set cals to calendars
  repeat with c in cals
    set today to current date
    set time of today to 0
    set tomorrow to today + 1 * days
    set evs to (every event of c whose start date >= today and start date < tomorrow)
    repeat with ev in evs
      set t to time string of (start date of ev)
      set out to out & t & "|" & (summary of ev) & linefeed
    end repeat
  end repeat
  return out
end run
"""

REMINDERS_APPLESCRIPT = """
on run
  set out to ""
  tell application "Reminders"
    repeat with r in (reminders of list "Reminders" whose completed is false)
      set out to out & (name of r) & linefeed
    end repeat
  end tell
  return out
end run
"""


def _live_calendar():
    if not _has_osascript():
        return [], None
    try:
        out = subprocess.run(["osascript", "-e", APPLESCRIPT],
                             capture_output=True, text=True, timeout=10)
        rows = []
        for line in (out.stdout or "").splitlines():
            if "|" in line:
                t, title = line.split("|", 1)
                rows.append({"time": t.strip(), "title": title.strip()})
        return rows, "live"
    except Exception:
        return [], "live"


def _live_reminders():
    if not _has_osascript():
        return [], None
    try:
        out = subprocess.run(["osascript", "-e", REMINDERS_APPLESCRIPT],
                             capture_output=True, text=True, timeout=10)
        rows = [{"title": ln.strip(), "done": False}
                for ln in (out.stdout or "").splitlines() if ln.strip()]
        return rows, "live"
    except Exception:
        return [], "live"


def _seed():
    for path in (CONTEXT_FILE, CONTEXT_FILE_ALT):
        try:
            with open(path) as fh:
                cfg = json.load(fh)
            cal = cfg.get("calendar_today", []) or []
            todos = cfg.get("todos_pending", []) or []
            if cal or todos:
                return cal, todos, "seed"
        except Exception:
            continue
    return [], [], "seed"


def collect():
    now = time.time()
    if _CACHE["data"] and now - _CACHE["t"] < CACHE_TTL:
        return _CACHE["data"]

    cal_live, cal_src = _live_calendar()
    rem_live, rem_src = _live_reminders()
    cal_seed, todo_seed, seed_src = _seed()

    # Provenance precedence: live rows if the platform can ever produce them
    # (macOS), else seed, else explicit live-empty. No fabrication.
    if _has_osascript():
        cal_final, cal_final_src = (cal_live, "live") if cal_live else ([], "live-empty")
        rem_final, rem_final_src = (rem_live, "live") if rem_live else ([], "live-empty")
        if not cal_final and cal_seed:
            cal_final, cal_final_src = cal_seed, "seed"
        if not rem_final and todo_seed:
            rem_final, rem_final_src = todo_seed, "seed"
    else:
        cal_final, cal_final_src = (cal_seed, "seed") if cal_seed else ([], "no-source")
        rem_final, rem_final_src = (todo_seed, "seed") if todo_seed else ([], "no-source")

    data = {
        "ok": True,
        "generated_at": time.strftime("%H:%M"),
        "calendar": {
            "source": cal_final_src,
            "events": cal_final,
            "live_count": len(cal_live),
        },
        "reminders": {
            "source": rem_final_src,
            "items": rem_final,
            "live_count": len(rem_live),
        },
        "weather": {"summary": None, "detail": None},  # filled by caller (chrome server has fetch_weather)
    }
    _CACHE["t"] = now
    _CACHE["data"] = data
    return data


if __name__ == "__main__":
    print(json.dumps(collect(), indent=2))