#!/usr/bin/env python3
"""
apple_mail.py — Apple Mail integration for GA-V9 Jeeves.

Reads and sends email through the user's existing Mail.app accounts
(AppleScript). No credentials stored — Mail.app is already signed in.

READ: strictly on-request. Jeeves never polls or announces mail.
SEND: requires explicit user confirmation before sending (caller enforces).

Design:
  mail_inbox(limit)     -> recent messages (index, from, subject, date, unread)
  mail_read(idx)        -> full body of message N (1-based from the inbox list)
  mail_search(query)    -> search subject/from across inbox
  mail_send(to, subject, body) -> compose + send (CONFIRM BEFORE CALLING)
"""
import re
import subprocess

OSASCRIPT = "/usr/bin/osascript"

# ── Persona title ───────────────────────────────────────────────────────────
# Set by the server from the persona registry. Canned responses use this
# instead of hardcoded "sir".
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

# Message body length cap so a huge email doesn't blow the TTS/response budget.
MAX_BODY_CHARS = 1500


def _run(script: str, timeout: int = 60) -> str:
    try:
        p = subprocess.run([OSASCRIPT, "-e", script], capture_output=True,
                           text=True, timeout=timeout)
        return (p.stdout or "").strip()
    except Exception:
        return ""


def _run_multiline(script_lines: list, timeout: int = 60) -> str:
    """Run a multi-statement AppleScript; return stdout."""
    return _run("\n".join(script_lines), timeout=timeout)


# ── Reading (on request only) ─────────────────────────────────────────────
def mail_inbox(limit: int = 8) -> list:
    """Recent inbox messages: [{index, from, subject, date, unread}]."""
    script = f"""
    tell application "Mail"
        set out to ""
        set msgs to messages of inbox
        set n to count of msgs
        if n > {limit} then set n to {limit}
        repeat with i from 1 to n
            set m to item i of msgs
            set out to out & i & "|" & (sender of m as text) & "|" & (subject of m) & "|" & (date received of m) & "|" & (read status of m) & linefeed
        end repeat
        return out
    end tell
    """
    out = _run(script)
    rows = []
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) >= 5 and parts[0].strip().isdigit():
            rows.append({
                "index": int(parts[0].strip()),
                "from": parts[1].strip(),
                "subject": parts[2].strip(),
                "date": parts[3].strip(),
                "unread": parts[4].strip() == "false",
            })
    return rows


def mail_read(idx: int) -> dict:
    """Read message body by inbox index (1-based). Returns {subject, from, body}."""
    script = f"""
    tell application "Mail"
        set msgs to messages of inbox
        if (count of msgs) < {idx} then return "ERR:INDEX"
        set m to item {idx} of msgs
        return (subject of m) & "~|~" & (sender of m as text) & "~|~" & (content of m)
    end tell
    """
    out = _run(script)
    if out.startswith("ERR:INDEX"):
        return {}
    parts = out.split("~|~", 2)
    if len(parts) < 3:
        return {"subject": parts[0] if parts else "", "from": "", "body": out}
    body = parts[2].strip()
    # Collapse whitespace; cap length
    body = re.sub(r"\s+", " ", body)
    if len(body) > MAX_BODY_CHARS:
        body = body[:MAX_BODY_CHARS] + "…"
    return {"subject": parts[0].strip(), "from": parts[1].strip(), "body": body}


def mail_search(query: str, limit: int = 6) -> list:
    """Search inbox by subject/from text. Returns [{index, from, subject, date}]."""
    q = query.replace('"', "").replace("\\", "")
    script = f"""
    tell application "Mail"
        set out to ""
        set msgs to (every message of inbox whose subject contains "{q}" or sender contains "{q}")
        set n to count of msgs
        if n > {limit} then set n to {limit}
        repeat with i from 1 to n
            set m to item i of msgs
            set out to out & i & "|" & (sender of m as text) & "|" & (subject of m) & "|" & (date received of m) & linefeed
        end repeat
        return out
    end tell
    """
    out = _run(script)
    rows = []
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) >= 4 and parts[0].strip().isdigit():
            rows.append({
                "index": int(parts[0].strip()),
                "from": parts[1].strip(),
                "subject": parts[2].strip(),
                "date": parts[3].strip(),
            })
    return rows


def mail_unread_count() -> int:
    out = _run('tell application "Mail" to count (every message of inbox whose read status is false)')
    try:
        return int(out.strip() or "0")
    except Exception:
        return 0


# ── Sending (requires confirmation by caller) ─────────────────────────────
def mail_send(to: str, subject: str, body: str) -> str:
    """Compose and send an email from the default account. CALLER MUST CONFIRM."""
    to = to.replace('"', "").replace("\\", "")
    subject = subject.replace('"', "").replace("\\", "")
    body = body.replace('"', "").replace("\\", "")
    script = f"""
    tell application "Mail"
        set newMsg to make new outgoing message with properties {{subject:"{subject}", content:"{body}", visible:false}}
        tell newMsg
            make new to recipient at end of to recipients with properties {{address:"{to}"}}
        end tell
        send newMsg
        return "SENT"
    end tell
    """
    out = _run(script, timeout=90)
    return out


# ── High-level dispatch for Jeeves ────────────────────────────────────────
def mail_action(intent: str, text: str) -> str:
    """Dispatch for the 'email' intent. Returns a response string.
    SEND proposals are NOT executed here — the caller handles confirmation.
    Applies the persona title (sir/dear) to the canned response.
    """
    return _t(_mail_action_impl(intent, text))


def _mail_action_impl(intent: str, text: str) -> str:
    """Internal dispatch — returns raw response with 'sir' placeholders."""
    lo = text.lower()

    # Word-boundary keyword helpers ("read" must not match inside "ready")
    def has_any(words):
        return any(re.search(r"\b" + re.escape(w) + r"\b", lo) for w in words)

    # Unread check first — most specific intent
    if has_any(("unread", "new mail", "new email", "any mail", "any email",
                "any new", "anything new")):
        n = mail_unread_count()
        if n == 0:
            return "No unread mail, sir."
        msgs = [m for m in mail_inbox(n) if m["unread"]]
        if not msgs:
            return f"You have {n} unread emails, sir. Shall I read them?"
        lines = [f"{m['index']}. {m['from']} — {m['subject']}" for m in msgs[:6]]
        return f"You have {n} unread emails, sir:\n" + "\n".join(lines)

    # Read/show — explicit read verbs
    if has_any(("read", "show", "open", "what does", "tell me about")):
        # "read email N" / "read the email about X" / "read my latest email"
        m = re.search(r"(?:email|message|mail)\s*(?:number\s*)?#?(\d+)", lo)
        if m:
            idx = int(m.group(1))
            msg = mail_read(idx)
            if not msg:
                return f"I couldn't find email number {idx}, sir."
            return (f"Email from {msg['from']} — '{msg['subject']}':\n{msg['body'][:300]}")
        # Find by subject keyword
        q = re.sub(r"^(read|show|open|what does|tell me about)\s+(the\s+)?(my\s+)?(email|message|mail)\s*(about|from|re:)?\s*", "", lo).strip(" .,!?")
        if q and len(q) > 2:
            results = mail_search(q)
            if results:
                first = results[0]
                msg = mail_read(first["index"])
                return (f"Here's the email from {msg['from']} — '{msg['subject']}':\n{msg['body'][:300]}")
            return f"No emails found matching '{q}', sir."
        # Default: latest unread email
        msgs = mail_inbox(1)
        if msgs:
            msg = mail_read(msgs[0]["index"])
            return (f"Your latest email is from {msg['from']} — '{msg['subject']}':\n{msg['body'][:300]}")
        return "Your inbox is empty, sir."

    # Search — explicit search verbs
    if has_any(("search", "find", "look for")):
        q = re.sub(r"^(search|find|look for)\s+(the\s+)?(my\s+)?(emails?|messages?|mail|inbox)\s*(about|from|for|re:)?\s*", "", lo).strip(" .,!?")
        if q and len(q) > 2:
            results = mail_search(q)
            if results:
                lines = [f"{r['index']}. {r['from']} — {r['subject']} ({r['date']})" for r in results]
                return "I found these emails, sir:\n" + "\n".join(lines)
            return f"No emails found matching '{q}', sir."
        return "What should I search for, sir?"

    # Send — requires an explicit send/compose verb (not just the word "email")
    if has_any(("send an email", "send a email", "send email", "send an e-mail",
                "compose", "write an email", "write a email", "draft an email",
                "email about", "email to", "send to")):
        # Parse: "email <to> <subject> <body>" — best effort.
        # Format expectations:
        #   "send an email to X about Y saying Z"  |  "email X about Y: Z"
        to = subject = body = ""
        m = re.search(r"(?:to)\s+([a-z0-9_.\-@ ]+?)\s+(?:about|subject)\s+(.+?)(?:\s+saying\s+|\s*:\s*)(.+)?", lo)
        if m:
            to = m.group(1).strip()
            subject = m.group(2).strip()
            body = (m.group(3) or "").strip()
        else:
            m = re.search(r"(?:about|subject)\s+(.+?)(?:\s+saying\s+|\s*:\s*)(.+)?", lo)
            if m:
                subject = m.group(1).strip()
                body = (m.group(2) or "").strip()
            m2 = re.search(r"(?:to)\s+([a-z0-9_.\-@ ]+?)(?:\s+(?:about|subject)\s+|$)", lo)
            if m2:
                to = m2.group(1).strip()
        if to and subject:
            if not body:
                return (f"I can send an email to {to} with subject '{subject}', sir. "
                        "What would you like the body to say?")
            return (f"I can send this email, sir:\n  To: {to}\n  Subject: {subject}\n  "
                    f"Body: {body[:120]}\nSay 'yes, send it' to confirm, or 'no, cancel' to stop.")
        if not to:
            return "Who should I email, sir?"
        return f"What should the subject be, sir?"

    # Default: show the inbox
    msgs = mail_inbox(8)
    if not msgs:
        return "Your inbox is empty, sir."
    lines = [f"{m['index']}. {'📩' if m['unread'] else '  '} {m['from']} — {m['subject']} ({m['date']})" for m in msgs]
    return "Here's your inbox, sir:\n" + "\n".join(lines)
