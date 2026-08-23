#!/usr/bin/env python3
"""
wda_control.py — WebDriverAgent control of the iOS device for GA-V9 Jeeves.

Mirrors tv_adb.py's interface so the server wires it the same way. Uses the
pymobiledevice3 `developer wda` subcommands (element-tree + tap-by-name +
button press) to drive the USB-connected iPad/iPhone with SEMANTIC control —
no pixel/coordinate guessing.

REQUIREMENTS (must be running for WDA to respond):
  1. `remote tunneld` running with sudo (forwards device ports / tunnel).
     e.g. sudo .../pymobiledevice3 remote tunneld
  2. The WebDriverAgentRunner TEST running on the device (Xcode → WebDriverAgent
     project → run WebDriverAgentRunner scheme as a test). WDA serves its
     WebDriver API on port 8100 ONLY while that test is running. It is NOT a
     tappable app.

Device target: USB-connected iOS 27 device (auto-detected via usbmux).

Capabilities:
  wda_action(text) -> Jeeves dispatcher (open app, tap, go home, read screen)
  open_app(name)   -> tap a home-screen app by name
  press(name)      -> press device button (home, lock, volumeup, ...)
  read_screen()    -> WDA element tree (what's on screen) via iphone_core wdalist
  health()         -> is tunneld + WDA reachable?
"""
import os
import re
import subprocess
import sys

# The tool that wraps pymobiledevice3 WDA (in GA-V9/tools/).
TOOLS = os.path.expanduser("~/Public/GA-V9/tools")
TOOL = os.path.join(TOOLS, "iphone_core.py")
# iphone_core.py shells out to `sys.executable -m pymobiledevice3`, so it must
# run under the spike venv that HAS pymobiledevice3 installed (the GA server
# venv doesn't). Point PY at that venv explicitly.
PY = os.path.expanduser("~/Public/GA-V9/.venv-iphone-spike/bin/python")
if not os.path.exists(PY):
    PY = sys.executable  # fallback: current interpreter

# Where tunneld listens (default 49151) — used for a quick reachability check.
TUNNELD_URL = os.getenv("GA_TUNNELD_URL", "http://127.0.0.1:49151/")

APP_ALIASES = {
    "weather": "Weather",
    "settings": "Settings",
    "photos": "Photos",
    "messages": "Messages",
    "calendar": "Calendar",
    "maps": "Maps",
    "camera": "Camera",
    "clock": "Clock",
    "notes": "Notes",
    "phone": "Phone",
    "safari": "Safari",
    "music": "Music",
    "tv": "TV",
    "facetime": "FaceTime",
    "mail": "Mail",
    "files": "Files",
    "app store": "App Store",
}


def _run_tool(args: list[str], timeout: int = 60) -> str:
    """Run iphone_core.py subcommand; return combined stdout+stderr trimmed."""
    cmd = [PY, TOOL] + args
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return "WDA command timed out."
    except Exception as e:
        return f"Error running WDA tool: {e}"


def health() -> str:
    """Is tunneld + WDA reachable?"""
    import urllib.request
    try:
        with urllib.request.urlopen(TUNNELD_URL, timeout=3) as resp:
            tunneld_ok = resp.status == 200
    except Exception:
        tunneld_ok = False
    # WDA: try a quick list-items; a non-empty element tree means it's live.
    tree = _run_tool(["wdalist"], timeout=30)
    wda_ok = "Failed to connect" not in tree and "No USB device" not in tree and "[" in tree
    parts = []
    parts.append(f"tunneld={'OK' if tunneld_ok else 'DOWN'}")
    parts.append(f"wda={'OK' if wda_ok else 'DOWN'}")
    return ", ".join(parts)


def _resolve_app(name: str) -> str:
    key = name.lower().strip()
    return APP_ALIASES.get(key, name.strip())


def open_app(name: str) -> str:
    """Tap a home-screen app by its semantic name."""
    app = _resolve_app(name)
    # We may be inside an app already; press home first so the app icon is
    # visible and tappable (WDA 404s if the target icon isn't on screen).
    home_out = _run_tool(["wdapress", "home"], timeout=30)
    import time as _t
    _t.sleep(1)
    out = _run_tool(["wdaopen", app], timeout=50)
    if "Failed to connect" in out or "No USB device" in out:
        return "The device's control link isn't ready, sir. The WebDriverAgent test needs to be running."
    if "could not find" in out:
        return f"I couldn't find the {app} app on the home screen, sir. Is it installed?"
    if "opened" in out:
        return f"Opening {app} on the iPad, sir."
    return f"I attempted to open {app}, sir, but I'm not certain it landed."


def press(name: str) -> str:
    """Press a device button (home, lock, volumeup, volumedown)."""
    out = _run_tool(["wdapress", name], timeout=40)
    if "Failed to connect" in out:
        return "The iPad's control link isn't ready, sir."
    return f"Pressed {name} on the iPad, sir."


def tree() -> str:
    """Return the element tree WITH frames (name + type + x/y/w/h) for in-app
    automation. Requires tunneld + WDA test running."""
    out = _run_tool(["wdatree"], timeout=90)
    if "Failed to connect" in out or "No USB device" in out:
        return "I can't get the iPad's element tree right now, sir — the control link isn't ready."
    if not out.strip() or out.strip() == "[]":
        return "The iPad's element tree is empty right now, sir."
    return out.strip()


def read_screen() -> str:
    """Return a clean summary of what's on the iPad screen (element names)."""
    out = _run_tool(["wdalist"], timeout=60)
    if "Failed to connect" in out or "No USB device" in out:
        return "I can't see the iPad screen right now, sir — the control link isn't ready."
    # Element tree is JSON; pull out names/labels, filtering internal/noise names.
    try:
        import json
        start = out.find("[")
        data = json.loads(out[start:])
        # Internal element-name noise to drop (XCTest identifiers, date ticks, etc.)
        NOISE = re.compile(
            r"(date-label|face-|widget-stack|hero\.|window-controls|resize-grabber|"
            r"SBSwitcher|AppSwitcher|StatusBar|Legibility|Horizontal scroll|page|"
            r"selected-date|month-view|iconic-date|label-view|\.app|sceneID|card:com)",
            re.I,
        )
        names = []
        for e in data:
            n = e.get("name") or e.get("label")
            if not n or not str(n).strip():
                continue
            n = str(n).strip()
            if NOISE.search(n) or len(n) < 2:
                continue
            names.append(n)
        if not names:
            return "The iPad screen shows no accessible elements right now, sir."
        # Dedupe, keep order
        seen, uniq = set(), []
        for n in names:
            if n not in seen:
                seen.add(n); uniq.append(n)
        return "On the iPad screen I can see: " + ", ".join(uniq[:20]) + "."
    except Exception:
        return out[:500]


def describe(prompt: str = "") -> str:
    """HYBRID: capture the iPad screen, send it to the LOCAL VLM (:8086) for
    visual interpretation, and return a spoken description. WDA gives element
    names/structure; the VLM reads the actual VISUAL CONTENT (weather, labels,
    on-screen text) that the element tree can't describe."""
    import base64
    import json
    import urllib.request
    # Capture via core-device screenshot (iphone_core screenshot -> /tmp)
    import tempfile
    tmp = tempfile.mktemp(suffix=".png")
    out = _run_tool(["screenshot", tmp], timeout=40)
    import os
    if not os.path.exists(tmp) or os.path.getsize(tmp) < 1000:
        return "I couldn't capture the iPad screen, sir — is the control link up?"
    try:
        b64 = base64.b64encode(open(tmp, "rb").read()).decode()
        text = prompt or (
            "Describe what is on this iPad screen in one or two sentences for an "
            "elderly person. Read any visible text or numbers out loud."
        )
        payload = {
            "model": "unsloth/Qwen3.5-9B",
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": text},
            ]}],
            "max_tokens": 200,
        }
        req = urllib.request.Request("http://127.0.0.1:8086/v1/chat/completions",
                                     data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.loads(r.read())
        desc = d["choices"][0]["message"]["content"].strip()
        return desc
    except Exception as e:
        print(f"[wda_control] vision error: {e}")
        return read_screen()  # fall back to the element-name summary
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def wda_action(text: str) -> str:
    """Jeeves dispatcher for iPad control via WebDriverAgent."""
    lo = text.lower().strip()

    # Health / status
    if "ipad" in lo and ("status" in lo or "ready" in lo or "connected" in lo or "link" in lo):
        return health()

    # Element tree (for automation/tapping reference)
    if re.search(r"\b(element tree|what can i tap|tappable|buttons)\b", lo) and "ipad" in lo:
        return tree()

    # Read screen — element names for "what's on"/"show"; VLM describe for
    # "read"/"describe" (richer: reads actual visual content + text).
    if re.search(r"\b(describe|read)\b", lo) and re.search(r"\b(ipad|screen|this|it)\b", lo):
        return describe()
    if (re.search(r"\bwhat(?:'s| is) (?:on|showing)\b", lo) and "ipad" in lo) \
       or "show me the ipad" in lo \
       or ("ipad screen" in lo and re.search(r"\b(show|see|tell)\b", lo)):
        return read_screen()

    # Home
    if re.search(r"\bgo home\b", lo) or re.search(r"\bhome screen\b", lo) or ("ipad" in lo and "home" in lo):
        return press("home")

    # Open / launch an app
    m = re.search(r"\b(?:open|launch|start|play|show)\s+(?:the\s+)?([a-z0-9 ]+?)\s+(?:app\s+)?(?:on\s+the\s+)?ipad", lo)
    if m:
        return open_app(m.group(1).strip())
    m = re.search(r"\b(?:open|launch)\s+(?:the\s+)?([a-z0-9 ]+?)\s+(?:app|program)", lo)
    if m:
        return open_app(m.group(1).strip())

    # Volume
    if "volume up" in lo or "louder" in lo:
        return press("volumeup")
    if "volume down" in lo or "quieter" in lo:
        return press("volumedown")

    return ("I can control the iPad, sir. Try things like: "
            "\"open the Weather app on the iPad\", \"go home on the iPad\", "
            "\"what's on the iPad screen\", or \"is the iPad control link ready?\".")


if __name__ == "__main__":
    print("WDA control tool for GA-V9.")
    print("Health:", health())
