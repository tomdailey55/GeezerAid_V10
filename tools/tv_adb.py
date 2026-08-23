#!/usr/bin/env python3
"""
tv_adb.py — ADB-based TV control for GA-V9 Jeeves (Fire TV, Google TV).

Complements cast_tools.py (Cast) and lg_tools.py (webOS). ADB gives what
Cast can't: power-off, input switching, screencap (screen reading), and
reliable app launch by Android package name.

Setup (one-time, per TV):
  1. Fire TV: Settings → My Fire TV → Developer options → ADB debugging ON
     (and "Apps from unknown sources" if sideloading). Note the IP.
  2. Google TV (Andrea's TCL): Settings → System → About → build number
     tap ×7 → Developer options → "Network debugging" ON. Note the IP.
  3. Add the IP to TVS dict below (or GA_TV_ADB_IPS env, comma-separated).
  4. First connect shows a pairing prompt on the TV — accept it.

Capabilities:
  connect(ip)          -> adb connect + auth
  launch_app(ip, name) -> launch by Android package (com.netflix.ninja etc.)
  power(ip, off)       -> power off / wake (via input keyevent)
  media(ip, action)    -> play/pause/stop/rewind/ff via keyevents
  screencap(ip, path)  -> capture screen to a PNG (DRM content = black)
  status(ip)           -> is device online? current focused app?
  tv_action(text)      -> Jeeves dispatcher
"""
import os
import re
import subprocess
import sys
import tempfile
import time

ADB = "/opt/homebrew/bin/adb"

# Device registry: name -> IP. Fill in after first discovery, or via env.
# LAN scan 2026-08-04 found TV-ish devices (7000=Fire TV remote, 8009=Cast):
#   192.168.12.112, .133 (Cast), .159, .174 (Cast), .186, .239
# Names TBD — enable ADB dev mode on each, then assign here.
TVS = {
    "theater": "192.168.12.174",     # Panasonic Fire TV Edition OLED (AFTLAS01, Fire OS 8.1.6.6)
    "andrea": "192.168.12.152",     # Master Bedroom TV (TCL Google TV, Android 12) — ADB enabled 2026-08-12
}
_env_ips = os.getenv("GA_TV_ADB_IPS", "")
if _env_ips:
    for entry in _env_ips.split(","):
        entry = entry.strip()
        if "=" in entry:
            name, ip = entry.split("=", 1)
            TVS[name.strip()] = ip.strip()

# Android package names for popular apps (Android TV / Fire TV)
PACKAGES = {
    "netflix": "com.netflix.ninja",
    "youtube": "com.google.android.youtube.tv",
    "plex": "com.plexapp.android",
    "prime": "com.amazon.avod.thirdpartyclient",
    "prime video": "com.amazon.avod.thirdpartyclient",
    "disney": "com.disney.disneyplus",
    "disney+": "com.disney.disneyplus",
    "hulu": "com.hulu.plus",
    "max": "com.wbd.hbo.max",
    "hbomax": "com.wbd.hbo.max",
    "apple tv": "com.apple.appletv",
    "spotify": "com.spotify.tv",
    "twitch": "com.twitch.tv.app",
    "crunchyroll": "com.crunchyroll.luna",
    "pluto": "com.plutotv.plutotv",
    "tubi": "com.tubitv",
    "peacock": "com.peacocktv.brownie",
    "paramount": "com.cbs.app",
    "paramount plus": "com.cbs.app",
}

# Common app package names on Fire TV / Android TV
FIRE_TV_PACKAGES = {
    "netflix": "com.netflix.ninja",
    "youtube": "com.google.android.youtube.tv",
    "prime": "com.amazon.avod.thirdpartyclient",
    "hulu": "com.hulu.plus",
    "disney": "com.disney.disneyplus",
    "plex": "com.plexapp.android",
    "max": "com.wbd.hbo.max",
    "paramount": "com.cbs.app",
    "apple tv": "com.apple.appletv",
}


def _sh(args: list, timeout: int = 30) -> str:
    """Run a shell command, return stdout (or '' on failure)."""
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return (p.stdout or "").strip()
    except Exception as e:
        print(f"[tv_adb] cmd error: {e}")
        return ""


def connect(ip: str) -> bool:
    """adb connect; returns True if device is online."""
    out = _sh([ADB, "connect", f"{ip}:5555"])
    online = _sh([ADB, "-s", f"{ip}:5555", "get-state"]) == "device"
    return online


def _resolve(device: str = "") -> str:
    """Resolve a device name/IP to an IP. Empty → first configured TV."""
    if device in TVS:
        return TVS[device]
    if device and re.match(r"^\d+\.\d+\.\d+\.\d+$", device):
        return device
    # fuzzy: "theater", "monitor", "andrea", "master bedroom" etc.
    low = device.lower()
    for name, ip in TVS.items():
        if low in name.lower():
            return ip
    if TVS:
        return next(iter(TVS.values()))
    return ""


def launch_app(device: str, app_name: str) -> str:
    ip = _resolve(device)
    if not ip:
        return ("I don't have any ADB TVs configured yet, sir. Enable developer "
                "mode on the TV and tell me its IP.")
    if not connect(ip):
        return f"I can't reach {device or ip} over ADB, sir. Is developer mode enabled?"
    pkg = PACKAGES.get(app_name.lower())
    if not pkg:
        return f"I don't know the package for {app_name} on Android TV, sir."
    out = _sh([ADB, "-s", f"{ip}:5555", "shell", "monkey", "-p", pkg, "1"])
    if "monkey aborted" in out or not out:
        # fallback: am start
        out2 = _sh([ADB, "-s", f"{ip}:5555", "shell", "am", "start", "-n", f"{pkg}/.MainActivity"])
        if "Error" in out2:
            return f"I couldn't launch {app_name}, sir — is it installed on {device or ip}?"
    return f"Launching {app_name} on {device or 'the TV'}, sir."


def power(device: str, state: str) -> str:
    ip = _resolve(device)
    if not ip:
        return "No ADB TVs configured, sir."
    if not connect(ip):
        return f"I can't reach {device or ip} over ADB, sir."
    if state == "off":
        # Fire TV: sleep keyevent 223 (sleep); Android TV: 26 (power)
        _sh([ADB, "-s", f"{ip}:5555", "shell", "input", "keyevent", "223"])
        return f"Powering off {device or 'the TV'}, sir."
    if state == "on":
        _sh([ADB, "-s", f"{ip}:5555", "shell", "input", "keyevent", "224"])
        return f"Waking {device or 'the TV'}, sir."
    return f"Unknown power state {state}, sir."


def media(device: str, action: str) -> str:
    ip = _resolve(device)
    if not ip:
        return "No ADB TVs configured, sir."
    if not connect(ip):
        return f"I can't reach {device or ip} over ADB, sir."
    keys = {
        "play": 126, "pause": 127, "stop": 86,
        "rewind": 89, "ff": 90, "next": 87, "prev": 88,
    }
    k = keys.get(action)
    if k is None:
        return f"I don't know how to {action} on Android TV, sir."
    _sh([ADB, "-s", f"{ip}:5555", "shell", "input", "keyevent", str(k)])
    return f"{action.capitalize()} on {device or 'the TV'}, sir."


def screencap(device: str = "", dest: str = "") -> str:
    """Capture the TV screen to a PNG. Returns the local path, or '' on
    failure. NOTE: DRM content (Netflix playback) captures black frames."""
    ip = _resolve(device)
    if not ip:
        return ""
    if not connect(ip):
        return ""
    remote = "/sdcard/jeeves_screen.png"
    _sh([ADB, "-s", f"{ip}:5555", "shell", "screencap", "-p", remote])
    if not dest:
        dest = tempfile.mktemp(suffix=".png", prefix="tv_screen_")
    out = _sh([ADB, "-s", f"{ip}:5555", "pull", remote, dest])
    if os.path.exists(dest) and os.path.getsize(dest) > 1000:
        return dest
    return ""


def status(device: str = "") -> str:
    ip = _resolve(device)
    if not ip:
        return "No ADB TVs configured, sir."
    if not connect(ip):
        return f"{device or 'The TV'} isn't reachable over ADB, sir."
    # Current foreground activity gives the running app
    out = _sh([ADB, "-s", f"{ip}:5555", "shell", "dumpsys", "activity", "activities",
               "|", "grep", "-E", "mResumedActivity|topResumedActivity"])
    m = re.search(r"([a-zA-Z0-9_.]+)/\.[a-zA-Z0-9_]+", out)
    pkg = m.group(1) if m else "unknown"
    for app, p in {**PACKAGES, **FIRE_TV_PACKAGES}.items():
        if p == pkg:
            return f"{device or 'The TV'} is showing {app}, sir."
    return f"{device or 'The TV'} is on (showing {pkg.split('.')[-1]}), sir."


def describe_screen(device: str = "", prompt: str = "") -> str:
    """Screencap the TV and describe it with the LOCAL MLX vision model
    (:8086, multimodal Qwen3.5-9B). Returns a spoken description.
    Fallback: cloud gateway if MLX vision is down.
    """
    path = screencap(device)
    if not path:
        return "I couldn't capture the screen, sir. Is the TV on with ADB enabled?"
    try:
        import base64
        import json
        import urllib.request
        b64 = base64.b64encode(open(path, "rb").read()).decode()
        text = prompt or "Describe what is showing on this TV screen in one or two sentences for an elderly person. Read any visible text out loud."
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
        print(f"[tv_adb] vision error: {e}")
        return f"I captured the screen to {path}, sir, but couldn't analyze it just now."


def tv_action(text: str) -> str:
    """Jeeves dispatcher for ADB TV control."""
    lo = text.lower()
    # Which device? Fire TVs / theater / andrea
    device = ""
    for name in TVS:
        if re.search(r"\b" + re.escape(name) + r"\b", lo):
            device = name
            break

    if "screenshot" in lo or ("screen" in lo and "read" in lo) or "what's on" in lo or "what is on" in lo or "showing" in lo:
        return describe_screen(device)

    if "turn off" in lo or "power off" in lo or "shut off" in lo:
        return power(device, "off")
    if "turn on" in lo or "wake" in lo:
        return power(device, "on")

    if "pause" in lo:
        return media(device, "pause")
    if re.search(r"\bplay\b", lo):
        return media(device, "play")
    if "stop" in lo:
        return media(device, "stop")
    if "rewind" in lo:
        return media(device, "rewind")
    if "fast forward" in lo or "skip" in lo:
        return media(device, "ff")

    m = re.search(r"\b(?:play|put on|open|launch|start)\s+([a-z0-9 ]+?)\s+(?:on|in)", lo)
    if m:
        return launch_app(device, m.group(1).strip())

    return ("What would you like me to do with the TV, sir? I can launch apps, "
            "control playback, capture the screen, or power it off.")


if __name__ == "__main__":
    print("ADB TVs configured:", TVS or "(none — set GA_TV_ADB_IPS or edit TVS)")
    if TVS:
        for name, ip in TVS.items():
            print(f"  {name}: {ip} — {'online' if connect(ip) else 'offline'}")
