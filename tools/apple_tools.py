#!/usr/bin/env python3
"""
apple_tools.py — native Apple app integration for GA-V9 Jeeves.

Wraps Apple's on-Mac apps so Jeeves can read/write the user's real data,
which then syncs to the iPad/iPhone via iCloud:

  Reminders  -> remindctl CLI          (create/list/complete, lists, due dates)
  Calendar   -> AppleScript Calendar  (today's/upcoming events, create events)
  Notes      -> memo CLI              (list/search/create notes)
  Messages   -> imsg CLI              (list chats, read history, send iMessage)
  Contacts   -> AppleScript Contacts  (search by name/number)

SAFETY: send-message and create-event require explicit confirmation text in the
query ("please send", "go ahead") — the calling handler enforces this.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
from datetime import datetime, timedelta

# ── CLI paths ──────────────────────────────────────────────────────────────
REMINDCTL = shutil.which("remindctl") or "/opt/homebrew/bin/remindctl"
MEMO = shutil.which("memo") or "/opt/homebrew/bin/memo"
IMSG = shutil.which("imsg") or "/opt/homebrew/bin/imsg"
OSASCRIPT = "/usr/bin/osascript"

# ── Persona title ───────────────────────────────────────────────────────────
# Set by the server from the persona registry (e.g. "sir" for Tom/Jeeves,
# "dear" for Andrea/Circe). Canned responses use this instead of hardcoded "sir".
TITLE = "sir"


def set_title(title: str) -> None:
    """Set the persona title used in canned responses."""
    global TITLE
    TITLE = title or "sir"


def _t(text: str) -> str:
    """Replace word-boundary 'sir' with the persona title in a response string."""
    if TITLE == "sir":
        return text
    return re.sub(r"\bsir\b", TITLE, text)


def _run(cmd: list, timeout: int = 30) -> str:
    """Run a command, return stdout (or '' on failure)."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (p.stdout or "").strip()
    except Exception:
        return ""


def _osascript(script: str, timeout: int = 30) -> str:
    return _run([OSASCRIPT, "-e", script], timeout=timeout)


# ── Reminders ──────────────────────────────────────────────────────────────
def reminders_today() -> list:
    out = _run([REMINDCTL, "today"])
    return [l for l in out.splitlines() if l.strip()]


def reminders_all() -> list:
    out = _run([REMINDCTL, "all"])
    return [l for l in out.splitlines() if l.strip()]


def reminders_overdue() -> list:
    out = _run([REMINDCTL, "overdue"])
    return [l for l in out.splitlines() if l.strip()]


def reminder_add(title: str, due: str = "", list_name: str = "") -> str:
    cmd = [REMINDCTL, "add", "--title", title]
    if due:
        cmd += ["--due", due]
    if list_name:
        cmd += ["--list", list_name]
    return _run(cmd)


def reminder_complete(id_or_index) -> str:
    return _run([REMINDCTL, "complete", str(id_or_index)])


def reminders_lists() -> list:
    out = _run([REMINDCTL, "list"])
    return [l for l in out.splitlines() if l.strip()]


# ── Calendar (AppleScript) ────────────────────────────────────────────────
def calendar_today() -> list:
    """Today's events as [{title, start, end, location, calendar}]."""
    script = """
    tell application "Calendar"
        set out to ""
        set todayStart to current date
        set time of todayStart to 0
        set todayEnd to todayStart + 1 * days
        repeat with cal in calendars
            repeat with ev in (every event of cal whose start date ≥ todayStart and start date < todayEnd)
                set out to out & (summary of ev) & "|" & (start date of ev as string) & "|" & (end date of ev as string) & "|" & (location of ev) & "|" & (name of cal) & linefeed
            end repeat
        end repeat
        return out
    end tell
    """
    out = _osascript(script)
    events = []
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) >= 5 and parts[0]:
            events.append({
                "title": parts[0].strip(),
                "start": parts[1].strip(),
                "end": parts[2].strip(),
                "location": parts[3].strip(),
                "calendar": parts[4].strip(),
            })
    return events


def calendar_upcoming(days: int = 7) -> list:
    script = f"""
    tell application "Calendar"
        set out to ""
        set s to current date
        set e to s + {days} * days
        repeat with cal in calendars
            repeat with ev in (every event of cal whose start date ≥ s and start date < e)
                set out to out & (summary of ev) & "|" & (start date of ev as string) & "|" & (location of ev) & "|" & (name of cal) & linefeed
            end repeat
        end repeat
        return out
    end tell
    """
    out = _osascript(script)
    events = []
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) >= 4 and parts[0]:
            events.append({
                "title": parts[0].strip(),
                "start": parts[1].strip(),
                "location": parts[2].strip(),
                "calendar": parts[3].strip(),
            })
    # Sort by start date string (ISO-ish) — best effort
    events.sort(key=lambda e: e["start"])
    return events


def calendar_create(title: str, start_str: str, end_str: str = "", calendar_name: str = "Calendar") -> str:
    """Create an event. start_str/end_str like '2026-08-05 14:00'."""
    script = f"""
    tell application "Calendar"
        set targetCal to first calendar whose name is "{calendar_name}"
        set newEvent to make new event at end of events of targetCal with properties {{summary:"{title}", start date:(date "{start_str}"), end date:(date "{end_str}")}}
        return summary of newEvent
    end tell
    """
    return _osascript(script)


# ── Notes (memo CLI) ──────────────────────────────────────────────────────
def notes_list(folder: str = "") -> list:
    cmd = [MEMO, "notes"]
    if folder:
        cmd += ["-f", folder]
    out = _run(cmd)
    return [l for l in out.splitlines() if l.strip()]


def notes_search(query: str) -> list:
    """Search notes. memo's -s is an interactive flag; we list all and filter
    locally for reliable CLI search."""
    q = query.lower()
    out = _run([MEMO, "notes"])
    matches = [l for l in out.splitlines() if q in l.lower()]
    return matches


def note_add(title: str, body: str = "") -> str:
    """Create a note. memo's non-interactive add takes a title; body via -b if supported."""
    cmd = [MEMO, "notes", "-a", title]
    if body:
        # memo may not support body on CLI; append as part of title with newline
        cmd = [MEMO, "notes", "-a", f"{title}\n\n{body}"]
    return _run(cmd)


# ── Messages (imsg CLI) ────────────────────────────────────────────────────
def _parse_ndjson(out: str) -> list:
    """Parse newline-delimited JSON (imsg outputs NDJSON, not an array)."""
    rows = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            continue
    return rows


def messages_chats(limit: int = 10) -> list:
    out = _run([IMSG, "chats", "--limit", str(limit), "--json"])
    return _parse_ndjson(out)


def messages_history(chat_id: str, limit: int = 20) -> list:
    out = _run([IMSG, "history", "--chat-id", chat_id, "--limit", str(limit), "--json"])
    return _parse_ndjson(out)


def message_send(to: str, text: str) -> str:
    """Send an iMessage/SMS. CALLER MUST CONFIRM with the user first."""
    return _run([IMSG, "send", "--to", to, "--text", text])


# ── Contacts (AppleScript) ─────────────────────────────────────────────────
def contacts_search(query: str = "") -> list:
    q = query.replace('"', "")
    if q:
        script = f"""
        tell application "Contacts"
            set out to ""
            repeat with p in (every person whose name contains "{q}")
                set nm to name of p
                set nums to ""
                repeat with ph in phones of p
                    set nums to nums & (value of ph) & ", "
                end repeat
                set out to out & nm & " ~ " & nums & linefeed
            end repeat
            return out
        end tell
        """
    else:
        script = """
        tell application "Contacts"
            set out to ""
            repeat with p in (every person)
                set nm to name of p
                set nums to ""
                repeat with ph in phones of p
                    set nums to nums & (value of ph) & ", "
                end repeat
                set out to out & nm & " ~ " & nums & linefeed
            end repeat
            return out
        end tell
        """
    out = _osascript(script)
    return [l for l in out.splitlines() if l.strip()]


# ── Find My (best-effort) ─────────────────────────────────────────────────
def findmy_devices() -> list:
    """Open FindMy and capture a screenshot for vision analysis.
    Returns the screenshot path (caller uses vision_analyze on it)."""
    _osascript('tell application "FindMy" to activate')
    path = "/tmp/findmy_devices.png"
    _run(["screencapture", "-w", "-o", path])
    return [path] if os.path.exists(path) else []


# ── Dispatch helper ────────────────────────────────────────────────────────
def _resolve_contact_number(name: str) -> dict:
    """Resolve a contact name to a phone number.
    Returns {"label", "number"} | {"ambiguous", "options"} | None."""
    import re as _re
    results = contacts_search(name)
    numbers = []
    for line in results:
        # Format: "Name ~ (941) 555-1234, (941) 555-5678, "
        m = _re.match(r"(.+?)\s*~\s*(.*)", line)
        if not m:
            continue
        label = m.group(1).strip()
        nums = [n.strip() for n in m.group(2).split(",") if n.strip()]
        for num in nums:
            numbers.append({"label": label, "number": num})
    if not numbers:
        return None
    # Dedupe by (label, number)
    seen = set()
    uniq = []
    for entry in numbers:
        key = (entry["label"], entry["number"])
        if key not in seen:
            seen.add(key)
            uniq.append(entry)
    if len(uniq) == 1:
        return uniq[0]
    # Multiple: normalize digits; if all share one number, use it; else flag ambiguous
    def _digits(s: str) -> str:
        return re.sub(r"\D", "", s)
    distinct_nums = {_digits(e["number"]) for e in uniq}
    if len(distinct_nums) == 1:
        return {"label": uniq[0]["label"], "number": uniq[0]["number"]}
    options = [f"{e['label']} ({e['number']})" for e in uniq[:6]]
    return {"ambiguous": True, "options": options}


def apple_action(intent: str, text: str) -> str:
    """High-level dispatch for Jeeves. Returns a human-readable response string.

    Applies the persona title (sir/dear) to the canned response.
    """
    return _t(_apple_action_impl(intent, text))


def _apple_action_impl(intent: str, text: str) -> str:
    """Internal dispatch — returns raw response with 'sir' placeholders."""
    lo = text.lower()

    if intent == "reminder":
        if "add" in lo or lo.startswith(("remind me to", "remind me about", "set a reminder")):
            # Extract the reminder text: strip "remind me to/about" / "set a reminder"
            title = re.sub(r"^(remind me to|remind me about|set a reminder|set a reminder to|don't let me forget to|don't forget to)\s*", "", lo)
            title = title.strip(" .,!?").capitalize()
            if not title or title.lower() in ("add", "create"):
                return "What would you like me to remind you about, sir?"
            result = reminder_add(title)
            return f"Very good, sir. I've added '{title}' to your Reminders."
        if "complete" in lo or "done" in lo or "finished" in lo:
            # Try to find the reminder id
            m = re.search(r"(?:complete|done|finished)\s+(?:reminder\s+)?#?(\d+)", lo)
            if m:
                result = reminder_complete(m.group(1))
                return f"Done, sir. Reminder {m.group(1)} completed."
            return "Which reminder would you like me to complete, sir?"
        if "overdue" in lo:
            items = reminders_overdue()
            return ("Your overdue reminders, sir:\n" + "\n".join(items)) if items else "No overdue reminders, sir."
        # Default: today's reminders
        items = reminders_today()
        return ("Your reminders for today, sir:\n" + "\n".join(items)) if items else "You have no reminders today, sir."

    if intent == "calendar":
        if "add" in lo or "create" in lo or "schedule" in lo and "add" in lo or "new event" in lo:
            # Parse: "add [event] on [date] at [time]" — best effort
            m = re.search(r"(?:add|create|schedule|set up)\s+(?:an?\s+)?([^,.;]+?)(?:\s+on\s+(\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?))?(?:\s+at\s+(\d{1,2}:\d{2}))?", lo)
            if m:
                title = m.group(1).strip().title()
                if title:
                    return f"I'd be happy to add '{title}' to your calendar, sir — but I'll need the date and time. e.g. 'Add dentist on 8/15 at 2pm'."
            return "I can add that to your calendar, sir — what date and time?"
        if "upcoming" in lo or "next" in lo or "week" in lo:
            events = calendar_upcoming(7)
            if not events:
                return "Nothing on your calendar for the next week, sir."
            lines = [f"• {e['title']} — {e['start']}" + (f" @ {e['location']}" if e['location'] else "") for e in events[:8]]
            return "Your calendar for the next week, sir:\n" + "\n".join(lines)
        events = calendar_today()
        if not events:
            return "Nothing on your calendar today, sir."
        lines = [f"• {e['title']} — {e['start'].split(', ')[1] if ', ' in e['start'] else e['start']}" + (f" @ {e['location']}" if e['location'] else "") for e in events[:8]]
        return "Here's your calendar today, sir:\n" + "\n".join(lines)

    if intent == "notes":
        if "add" in lo or "create" in lo or "write" in lo or "save" in lo:
            title = re.sub(r"^(add|create|write|save)\s+(a\s+)?(note\s+)?(to\s+)?(my\s+)?(notes?\s+)?", "", lo).strip(" .,!?").capitalize()
            if title:
                note_add(title)
                return f"Done, sir. I've saved '{title}' to your Notes."
            return "What should the note say, sir?"
        if "search" in lo or "find" in lo or "look" in lo:
            q = re.sub(r"^(search|find|look)\s+(for\s+)?(my\s+)?(notes?\s+)?(for\s+)?", "", lo).strip(" .,!?")
            if q:
                results = notes_search(q)
                if results:
                    return "I found these notes, sir:\n" + "\n".join(results[:5])
                return f"No notes found matching '{q}', sir."
            return "What should I search for, sir?"
        notes = notes_list()
        if not notes:
            return "You have no notes, sir."
        return "Your notes, sir:\n" + "\n".join(notes[:8])

    if intent == "message":
        # Sending requires explicit confirmation — always return a confirmation ask
        # Split recipient from body on separator words ("saying", "that", ":").
        recipient, body = "", ""
        sep_match = re.search(r"\s+(?:saying|that|about)\s+|\s*:\s*", lo)
        if sep_match:
            recipient = lo[:sep_match.start()].strip()
            body = lo[sep_match.end():].strip()
        else:
            m = re.search(r"(?:text|message|send)\s+(.+)$", lo)
            if m:
                recipient = m.group(1).strip()
        # Strip the leading verb from recipient
        recipient = re.sub(r"^(?:text|message|send|send a text to|send a message to)\s+", "", recipient).strip()
        recipient = recipient.rstrip("'s")
        if recipient and body:
            # Resolve the recipient name to a phone number via Contacts so
            # imsg gets a valid target (a bare name fails with
            # "Multiple contacts match" or "contact not found").
            resolved = _resolve_contact_number(recipient)
            if resolved is None:
                return (f"I couldn't find a unique contact for '{recipient}', sir. "
                        "Please give me their number or a more specific name.")
            if resolved.get("ambiguous"):
                options = "\n".join(f"  • {c}" for c in resolved["options"][:4])
                return (f"There are multiple contacts matching '{recipient}', sir:\n{options}\n"
                        "Which one did you mean?")
            return (f"I can send '{body}' to {resolved['label']} ({resolved['number']}), sir. "
                    f"Say 'yes, send it' to confirm, or 'no, cancel' to stop.")
        if recipient:
            return f"What should I say to {recipient}, sir?"
        return "Who would you like me to message, sir?"

    if intent == "contacts":
        # Strip leading verbs and trailing request words, keep the name
        q = lo
        for prefix in ("find ", "look up ", "get ", "search ", "what is ", "what's ",
                       "the number for ", "the phone number for ", "contact info for ",
                       "number for ", "phone number for "):
            if q.startswith(prefix):
                q = q[len(prefix):]
                break
        for suffix in (" phone number", " phone", " number", " contact info", " contact",
                       " information", " please", " sir", " please sir"):
            if q.endswith(suffix):
                q = q[: -len(suffix)]
                break
        q = q.strip(" .,!?")
        # Strip possessives: "andrea's" -> "andrea"
        if q.endswith("'s"):
            q = q[:-2]
        if q:
            results = contacts_search(q)
            if results:
                return "I found these contacts, sir:\n" + "\n".join(results[:5])
            return f"No contacts found matching '{q}', sir."
        results = contacts_search()
        return "Your contacts, sir:\n" + "\n".join(results[:8])

    if intent == "call":
        return ("I can't place calls from the Mac, sir — but I can find the number "
                "and open FaceTime if you like. Who would you like to call?")

    return "I'm not sure how to help with that yet, sir."
