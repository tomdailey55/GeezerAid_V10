#!/usr/bin/env python3
"""
lg_tools.py — LG webOS TV control for GA-V9 Jeeves.

Controls LG webOS TVs via the local ThinQ/WebSocket API (aiopylgtv).
Unlike Cast devices, LG TVs support FULL control: power on/off, input
switching, app launch, media transport, volume.

One-time setup: first connection shows a pairing prompt ON THE TV —
someone must click "OK" (optionally with a PIN). After that the client
key is stored and reconnects silently.

Capabilities:
  discover()        -> scan LAN for webOS TVs (best-effort; usually needs IP)
  launch_app()      -> launch app by name (Netflix, YouTube, Plex...)
  media_control()   -> play / pause / stop / rewind / fast_forward
  volume()          -> up / down / mute / set
  power()           -> on / off / status
  input_switch()    -> switch HDMI input
  lg_action()       -> Jeeves dispatcher
"""
import asyncio
import os
import re
import sys
from typing import Optional

sys.path.insert(0, "/Users/tomdailey/.venvs/jeeves-voice/lib/python3.12/site-packages")

from aiopylgtv import WebOsClient  # noqa: E402

# LG webOS app IDs (standard across models)
LG_APPS = {
    "netflix": "netflix",
    "youtube": "youtube.leanback.v4",
    "plex": "com.plexapp.android",
    "prime": "amazon",
    "prime video": "amazon",
    "disney": "com.disney.disneyplus",
    "disney+": "com.disney.disneyplus",
    "hulu": "com.hulu.plus",
    "max": "com.wbd.hbo.max",
    "hbomax": "com.wbd.hbo.max",
    "apple tv": "com.apple.appletv",
    "spotify": "com.spotify.service",
    "twitch": "com.twitch.tv.app",
    "crunchyroll": "com.crunchyroll.luna",
    "pluto": "com.plutotv.plutotv",
    "tubi": "com.tubitv",
    "peacock": "com.peacocktv.brownie",
}

# Per-device client key cache (avoids re-pairing on every call)
KEY_DIR = os.path.expanduser("~/Public/GA-V9/tools/.lg_keys")
os.makedirs(KEY_DIR, exist_ok=True)


def _key_path(ip: str) -> str:
    return os.path.join(KEY_DIR, ip.replace(".", "_") + ".key")


def _client(ip: str):
    """Create a WebOsClient with the stored client key (if any)."""
    key = ""
    kp = _key_path(ip)
    if os.path.exists(kp):
        key = open(kp).read().strip()
    return WebOsClient(ip, key=key or None)


def _save_key(ip: str, client) -> None:
    try:
        kp = _key_path(ip)
        with open(kp, "w") as f:
            f.write(client.client_key)
    except Exception:
        pass


def _run(coro_factory, timeout: float = 15):
    """Run an async operation with its own event loop (safe from sync callers)."""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(asyncio.wait_for(coro_factory(), timeout))
    except asyncio.TimeoutError:
        return None
    except Exception as e:
        print(f"[lg] error: {e}")
        return None
    finally:
        loop.close()


def _with_client(ip: str, action):
    """Connect, run action(client), close. Returns action result or None."""
    client = _client(ip)

    async def go():
        await client.connect()
        try:
            return await action(client)
        finally:
            await client.disconnect()

    result = _run(go)
    if result is None and not os.path.exists(_key_path(ip)):
        return "PAIRING_REQUIRED"
    return result


# ── Discovery (best-effort) ───────────────────────────────────────────────
def discover() -> list:
    """LG TVs don't do mDNS discovery well via this lib. If the user knows
    the IP, config it; otherwise return a hint. (Home Assistant / manual IP
    are the reliable paths.)"""
    return []  # discovery is unreliable; prefer configured IPs


# ── Core operations ───────────────────────────────────────────────────────
def launch_app(ip: str, app_name: str) -> str:
    app_id = LG_APPS.get(app_name.lower().strip())
    if not app_id:
        return f"I don't have an app ID for {app_name} on the LG, sir."
    result = _with_client(ip, lambda c: c.launch_app(app_id))
    if result == "PAIRING_REQUIRED":
        return ("I need to pair with the LG TV first, sir — a prompt should be "
                "showing on the screen now. Please confirm it, then ask again.")
    return f"Launching {app_name} on the LG TV, sir." if result is not None else \
        "I couldn't reach the LG TV, sir. Is it on and on the same network?"


def media_control(ip: str, action: str) -> str:
    actions = {"play": "play", "pause": "pause", "stop": "stop",
               "rewind": "rewind", "ff": "fast_forward", "fast forward": "fast_forward"}
    method = actions.get(action.lower())
    if not method:
        return f"I don't know how to {action} on the LG, sir."
    result = _with_client(ip, lambda c: getattr(c, method)())
    if result == "PAIRING_REQUIRED":
        return "I need to pair with the LG TV first, sir — please confirm the prompt on screen."
    return f"{action.capitalize()} on the LG TV, sir." if result is not None else \
        "I couldn't reach the LG TV, sir."


def volume(ip: str, direction: str = "", amount: int = 0) -> str:
    async def act(c):
        if direction == "up":
            await c.volume_up()
        elif direction == "down":
            await c.volume_down()
        elif direction == "mute":
            await c.set_mute(True)
        elif direction == "unmute":
            await c.set_mute(False)
        elif direction == "set" and amount:
            await c.set_volume(amount)
        else:
            vol = await c.get_volume()
            return f"Volume on the LG TV is at {vol}%, sir."
        return True
    result = _with_client(ip, act)
    if result == "PAIRING_REQUIRED":
        return "I need to pair with the LG TV first, sir — please confirm the prompt on screen."
    if isinstance(result, str):
        return result
    labels = {"up": "Volume up", "down": "Volume down", "mute": "Muted",
              "unmute": "Unmuted", "set": f"Volume set to {amount}%"}
    return f"{labels.get(direction, 'Adjusted')} on the LG TV, sir." if result is not None else \
        "I couldn't reach the LG TV, sir."


def power(ip: str, state: str = "") -> str:
    async def act(c):
        if state == "on":
            await c.power_on()
            return "Powering on the LG TV, sir."
        if state == "off":
            await c.power_off()
            return "Powering off the LG TV, sir."
        on = await c.is_on()
        return f"The LG TV is {'on' if on else 'off'}, sir."
    result = _with_client(ip, act)
    if result == "PAIRING_REQUIRED":
        return "I need to pair with the LG TV first, sir — please confirm the prompt on screen."
    return result if isinstance(result, str) else "I couldn't reach the LG TV, sir."


def input_switch(ip: str, label: str) -> str:
    async def act(c):
        inputs = await c.get_inputs()
        for inp in inputs:
            if label.lower() in (inp.get("label", "") or "").lower():
                await c.set_input(inp["id"])
                return f"Switched the LG TV to {inp.get('label')}, sir."
        return f"I couldn't find an input called '{label}' on the LG TV, sir."
    result = _with_client(ip, act)
    if result == "PAIRING_REQUIRED":
        return "I need to pair with the LG TV first, sir — please confirm the prompt on screen."
    return result if isinstance(result, str) else "I couldn't reach the LG TV, sir."


# ── Jeeves dispatcher ─────────────────────────────────────────────────────
LG_TV_IP = os.getenv("GA_LG_TV_IP", "")  # configure via launch agent env


def lg_action(text: str) -> str:
    """Dispatch for the 'lg_tv' intent. Returns a response string."""
    if not LG_TV_IP:
        return ("I'm not configured with the LG TV's address yet, sir. "
                "Once you tell me its IP, I can control it.")
    lo = text.lower()

    # Power
    if "turn off" in lo or "power off" in lo or "shut off" in lo:
        return power(LG_TV_IP, "off")
    if "turn on" in lo or "power on" in lo:
        return power(LG_TV_IP, "on")

    # Volume
    if "volume" in lo or "louder" in lo or "quieter" in lo or "mute" in lo:
        if "up" in lo or "louder" in lo:
            return volume(LG_TV_IP, "up")
        if "down" in lo or "quieter" in lo:
            return volume(LG_TV_IP, "down")
        if "mute" in lo:
            return volume(LG_TV_IP, "mute")
        m = re.search(r"(\d+)\s*%", lo)
        if m:
            return volume(LG_TV_IP, "set", int(m.group(1)))
        return volume(LG_TV_IP)

    # Transport
    if "pause" in lo:
        return media_control(LG_TV_IP, "pause")
    if re.search(r"\bplay\b", lo) and "on" not in lo:
        return media_control(LG_TV_IP, "play")
    if "stop" in lo:
        return media_control(LG_TV_IP, "stop")
    if "rewind" in lo:
        return media_control(LG_TV_IP, "rewind")
    if "fast forward" in lo or "skip" in lo:
        return media_control(LG_TV_IP, "ff")

    # App launch: "play netflix on the lg" / "put on youtube on the lg"
    m = re.search(r"\b(?:play|put on|open|launch|start)\s+([a-z0-9 ]+?)\s+(?:on|in)", lo)
    if m:
        app = m.group(1).strip()
        return launch_app(LG_TV_IP, app)

    # Input: "switch the lg to hdmi 2"
    m = re.search(r"\b(?:switch|change|go to)\s+(?:the\s+)?(?:lg\s+)?(?:tv\s+)?(?:to\s+)?(.+)$", lo)
    if m and ("input" in lo or "hdmi" in lo):
        return input_switch(LG_TV_IP, m.group(1).strip())

    return ("What would you like me to do with the LG TV, sir? I can launch apps, "
            "control playback, adjust volume, switch inputs, or power it on and off.")


if __name__ == "__main__":
    print(f"LG TV IP configured: {LG_TV_IP or '(none — set GA_LG_TV_IP)'}")
