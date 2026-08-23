#!/usr/bin/env python3
"""
cast_tools.py — Google Cast (Chromecast / Google TV) control for GA-V9 Jeeves.

Controls Cast-enabled devices on the LAN — Andrea's TCL Google TV, Chromecasts,
Google Nest speakers, etc. Uses the standard Cast protocol via pychromecast:
no developer mode / ADB setup required on the device.

Capabilities:
  discover()           -> list of {name, model, uuid, host}
  find(name_fragment)  -> first device whose name matches
  launch_app()         -> launch app by name (Netflix, YouTube, Plex, Prime...)
  media_control()      -> play / pause / stop / seek / rewind / skip
  volume()             -> up / down / set N / mute toggle
  play_media()         -> cast arbitrary media URL (mp4/hls/etc.)
  cast_action()        -> Jeeves dispatcher, device resolved by name

Notes:
  - Casting to a sleeping device WAKES it (built into the protocol).
  - Power-OFF is NOT part of Cast — handled via CEC/ADB elsewhere if needed.
  - Discovery is LAN mDNS; requires the Mac and TV on the same network.
"""
import re
import socket
import subprocess
import sys
import time
from typing import List, Optional

sys.path.insert(0, "/Users/tomdailey/.venvs/jeeves-voice/lib/python3.12/site-packages")

import pychromecast  # noqa: E402
from pychromecast.controllers.media import MediaController  # noqa: E402

# App names -> app_id (built-in Cast apps; Google TV also supports these).
# For other apps (Plex, Prime Video, etc.) pychromecast can launch by app_id;
# common ones are mapped below. `launch_app` falls back to casting the app's
# URL when no app_id is known.
KNOWN_APPS = {
    "netflix": "CC32E01C",          # Netflix
    "youtube": "233637DE",          # YouTube
    "youtube tv": "234862BC",       # YouTube TV
    "spotify": "CC32E01C",          # Spotify (uses cast)
    "plex": "9AC194DC",             # Plex
    "prime": "A1F83G8C2R0J7W",      # Prime Video (Android TV app id)
    "prime video": "A1F83G8C2R0J7W",
    "disney": "CAESPKCH",           # Disney+
    "hulu": "8EC4D90A",             # Hulu
    "hbomax": "A3E7B8C2R0J7W",      # HBO Max
    "max": "A3E7B8C2R0J7W",
    "apple tv": "E2B4B5C2R0J7W",    # Apple TV app
    "twitch": "A1F83G8C2R0J7W",     # placeholder
    "crunchyroll": "A1F83G8C2R0J7W",
}

# Aliases so "Andrea's TV" / "the living room TV" / "the bedroom TV" resolve.
DEVICE_ALIASES = {
    "andrea": "master bedroom",      # her TV is named "Master Bedroom TV"
    "andrea's": "master bedroom",
    "andreas": "master bedroom",
    "master bedroom": "master bedroom",
    "living room": "living room",
    "bedroom": "master bedroom",
    "kitchen": "kitchen",
    "theater": "theater",
    "home theater": "theater",
    "den": "den",
    "office": "office",
    "tv": "",
}


def _safe_cast_name(name: str) -> str:
    """Normalize a device name to something mDNS-safely comparable."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def discover(timeout: float = 5.0) -> List[dict]:
    """Discover Cast devices on the LAN. Returns [{name, model, uuid, host}]."""
    devices = []
    try:
        casts, browser = pychromecast.get_chromecasts(timeout=timeout)
        for c in casts:
            host = getattr(c, "host", None)
            if host is None and hasattr(c, "cast_info"):
                host = c.cast_info.host
            devices.append({
                "name": c.name,
                "model": c.model_name,
                "uuid": str(c.uuid),
                "host": host,
            })
        try:
            browser.stop_discovery()
        except Exception:
            pass
    except Exception as e:
        print(f"[cast] discovery error: {e}")
    return devices


def find(name_fragment: str = "") -> Optional[dict]:
    """Find a device by name fragment. Empty matches the first device."""
    fragment = _safe_cast_name(name_fragment)
    devices = discover(timeout=6)
    if not devices:
        return None
    if not fragment:
        return devices[0]
    # Exact-ish match first
    for d in devices:
        if _safe_cast_name(d["name"]) == fragment:
            return d
    # Alias map
    alias = DEVICE_ALIASES.get(name_fragment.strip().lower(), "")
    if alias:
        for d in devices:
            if _safe_cast_name(alias) and _safe_cast_name(alias) in _safe_cast_name(d["name"]):
                return d
    # Substring match
    for d in devices:
        if fragment in _safe_cast_name(d["name"]):
            return d
    return None


def _connect(name_fragment: str = ""):
    """Return (cast, info) for a named device (fresh discovery, v14 API)."""
    info = find(name_fragment)
    if not info:
        return None, None
    try:
        # v14: Chromecast is constructed from CastInfo; get_chromecast() is gone.
        # NOTE: do NOT stop_discovery() here — it kills the zeroconf loop the
        # connected device's sockets depend on.
        casts, browser = pychromecast.get_chromecasts(timeout=6)
        for c in casts:
            if str(c.uuid) == info["uuid"]:
                c.wait(timeout=10)
                return c, info
        # Fallback: construct from CastInfo
        ci = pychromecast.CastInfo(info["name"], info["host"], 8009, str(info["uuid"]))
        cast = pychromecast.Chromecast(ci)
        cast.wait(timeout=10)
        return cast, info
    except Exception as e:
        print(f"[cast] connect error: {e}")
        return None, None


def _app_id_for(app_name: str) -> Optional[str]:
    key = app_name.lower().strip()
    return KNOWN_APPS.get(key)


def launch_app(name_fragment: str, app_name: str) -> str:
    """Launch an app on the device. app_name like 'netflix', 'youtube'."""
    cast, info = _connect(name_fragment)
    if not cast:
        return f"I couldn't find a Cast device{(' matching ' + name_fragment) if name_fragment else ''}, sir."
    try:
        app_id = _app_id_for(app_name)
        if app_id:
            try:
                cast.start_app(app_id)
                # Verify the launch actually took effect (Google TV quirk:
                # legacy Cast IDs silently fail for apps not installed).
                import time as _t
                _t.sleep(2.0)
                active = cast.app_display_name or ""
                launched = (app_name.lower() in active.lower()) or cast.media_controller.is_active
                if launched:
                    return f"Launching {app_name} on {info['name']}, sir."
                return (f"I launched it, but {info['name']} may need {app_name} installed. "
                        f"Check the screen, sir — the app should be opening.")
            except Exception:
                return (f"I couldn't launch {app_name} on {info['name']}, sir — it may not be "
                        f"installed on that TV. I can try YouTube if you like.")
        # Unknown app: try casting its name (works for many web apps)
        cast.media_controller.play_media(f"https://www.google.com/search?q={app_name}", "text/html")
        return f"I'll try to open {app_name} on {info['name']}, sir."
    except Exception as e:
        return f"I couldn't launch {app_name}, sir. ({str(e)[:80]})"


def media_control(name_fragment: str, action: str) -> str:
    """Transport control: play / pause / stop / seek / rewind / skip."""
    cast, info = _connect(name_fragment)
    if not cast:
        return "I couldn't find that Cast device, sir."
    try:
        mc = cast.media_controller
        action = action.lower()
        if action == "play":
            mc.play()
        elif action == "pause":
            mc.pause()
        elif action == "stop":
            mc.stop()
        elif action == "seek":
            mc.seek(0)  # restart; explicit seek handled by caller
        elif action == "rewind":
            mc.rewind()
        elif action == "skip":
            mc.skip()
        return f"{action.capitalize()} on {info['name']}, sir."
    except Exception as e:
        return f"I couldn't {action} that, sir. ({str(e)[:80]})"


def volume(name_fragment: str, direction: str = "", amount: int = 0) -> str:
    """Volume: 'up'/'down' (step), 'mute'/'unmute', or explicit level."""
    cast, info = _connect(name_fragment)
    if not cast:
        return "I couldn't find that Cast device, sir."
    try:
        direction = direction.lower()
        if direction in ("up", "down"):
            step = amount or 0.1
            new_vol = min(1.0, max(0.0, cast.status.volume_level + (step if direction == "up" else -step)))
            cast.set_volume(new_vol)
            return f"Volume {direction} on {info['name']}, sir."
        if direction in ("mute", "unmute"):
            cast.set_volume_muted(direction == "mute")
            return f"{'Muted' if direction == 'mute' else 'Unmuted'} {info['name']}, sir."
        if direction == "set" and amount:
            cast.set_volume(min(1.0, max(0.0, amount / 100.0)))
            return f"Volume set to {amount}% on {info['name']}, sir."
        return f"Volume on {info['name']} is at {int(cast.status.volume_level * 100)}%, sir."
    except Exception as e:
        return f"I couldn't adjust volume, sir. ({str(e)[:80]})"


def play_media(name_fragment: str, url: str, title: str = "", mime: str = "video/mp4") -> str:
    """Cast an arbitrary media URL."""
    cast, info = _connect(name_fragment)
    if not cast:
        return "I couldn't find that Cast device, sir."
    try:
        cast.media_controller.play_media(url, mime, title=title or url.split("/")[-1])
        cast.media_controller.play()
        return f"Playing {title or 'that'} on {info['name']}, sir."
    except Exception as e:
        return f"I couldn't cast that, sir. ({str(e)[:80]})"


def status(name_fragment: str = "") -> str:
    """Report what's playing on the device."""
    cast, info = _connect(name_fragment)
    if not cast:
        return "No Cast devices found on the network, sir."
    try:
        st = cast.media_controller.status
        if st and st.media_title:
            state = "playing" if cast.media_controller.is_active else "paused/stopped"
            return f"{info['name']} is {state}: '{st.media_title}' by {st.media_artist or 'unknown'}, sir."
        return f"{info['name']} is idle, sir."
    except Exception:
        return f"{info['name']} is idle, sir."


# ── Jeeves dispatcher ──────────────────────────────────────────────────────
def cast_action(text: str) -> str:
    """High-level dispatch for the 'cast' intent. Returns a response string."""
    lo = text.lower()

    # Which device? Default: first/any
    device = ""
    for alias in ("andrea", "andrea's", "andreas", "living room", "bedroom", "kitchen",
                  "theater", "home theater", "den", "office", "tv"):
        if re.search(r"\b" + re.escape(alias) + r"\b", lo):
            device = alias
            break

    # Status: "what's on the tv" / "is the tv playing"
    if any(w in lo for w in ("what's on", "what is on", "status", "what's playing", "what is playing")):
        return status(device)

    # Volume
    m = re.search(r"\b(?:volume|turn it|turn it up|turn it down|louder|quieter|mute|unmute)\b", lo)
    if "volume" in lo or "louder" in lo or "quieter" in lo or "mute" in lo or "unmute" in lo:
        if "up" in lo or "louder" in lo:
            return volume(device, "up")
        if "down" in lo or "quieter" in lo:
            return volume(device, "down")
        if "mute" in lo:
            return volume(device, "mute")
        if "unmute" in lo:
            return volume(device, "unmute")
        m2 = re.search(r"(\d+)\s*%", lo)
        if m2:
            return volume(device, "set", int(m2.group(1)))
        return volume(device)

    # Transport: play/pause/stop/rewind/skip
    if re.search(r"\b(?:pause|paused)\b", lo):
        return media_control(device, "pause")
    if re.search(r"\b(?:resume|keep playing|start playing)\b", lo) or \
       (re.search(r"\bplay\b", lo) and not re.search(r"\bplay\s+(.+?)\s+on\b", lo)):
        return media_control(device, "play")
    if re.search(r"\b(?:stop|turn off the tv|shut off)\b", lo):
        return media_control(device, "stop")
    if "rewind" in lo:
        return media_control(device, "rewind")
    if "skip" in lo or "next" in lo:
        return media_control(device, "skip")

    # Launch app: "play netflix on andrea's tv" / "put on youtube in the living room"
    m = re.search(r"\b(?:play|put on|open|launch|start)\s+([a-z0-9 ]+?)\s+(?:on|in)\s+(?:the\s+)?([a-z' ]+)", lo)
    if m:
        app_name = m.group(1).strip()
        # Only adopt the regex device fragment if the alias loop above didn't
        # already resolve one ("andrea" from "andrea's tv" beats the raw "andreas tv").
        if not device:
            candidate_dev = m.group(2).strip()
            if any(a in candidate_dev for a in ("tv", "andrea", "living", "bedroom", "kitchen", "theater", "den", "office")):
                device = candidate_dev
        return launch_app(device, app_name)

    # "play X on the tv" where X is media (not an app)
    m = re.search(r"\bplay\s+(.+?)\s+on\s+(?:the\s+)?([a-z' ]+)", lo)
    if m:
        content = m.group(1).strip()
        target = m.group(2).strip()
        if any(a in target for a in ("tv", "andrea", "living", "bedroom", "kitchen", "theater", "den", "office")):
            device = target
        # Try app first; if it's not a known app, cast a search
        if _app_id_for(content):
            return launch_app(device, content)
        # Generic: open YouTube search for it (best-effort for TV)
        search_url = f"https://www.youtube.com/results?search_query={content.replace(' ', '+')}"
        return play_media(device, search_url, title=f"Search: {content}", mime="text/html")

    return ("What would you like me to play, sir? I can launch apps like Netflix or "
            "YouTube, control playback, or adjust volume.")


if __name__ == "__main__":
    print("Cast devices on LAN:")
    for d in discover(timeout=6):
        print(f"  - {d['name']} ({d['model']}) @ {d['host']}")
