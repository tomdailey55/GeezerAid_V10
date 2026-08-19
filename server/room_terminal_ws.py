#!/usr/bin/env python3
"""
GeezerAid Room Terminal WebSocket Server
Handles always-on room terminals: wake-word, audio streaming, STT, TTS.
Runs alongside server_v9.py on a separate port (default 8767).

Architecture:
  room terminal (browser) --WSS--> room_terminal_ws.py (this file)
                                      |
                                      |- STT (Whisper API or local)
                                      |- POST /chat to server_v9.py:8766
                                      |- Stream TTS audio back to terminal

Config (env vars):
  GA_WS_PORT         — WebSocket port (default 8767)
  GA_HTTP_PORT       — V9 HTTP server port (default 8766)
  GA_STT_PROVIDER    — "openai" (cloud) or "local" (whisper.cpp) (default: openai)
  GA_OPENAI_API_KEY  — OpenAI/Nous API key for STT (defaults to NOUS_API_KEY)
  GA_STT_MODEL       — Whisper model (default: whisper-1)
  GA_ROOM_CONFIG     — JSON mapping: { "192.168.1.50": "kitchen", ... }

Room Detection:
  - First priority: URL query param ?room=kitchen
  - Second: client IP lookup in GA_ROOM_CONFIG
  - Fallback: "unknown"
"""

import os, sys, json, time, base64, asyncio, tempfile, re, subprocess
import websockets
from urllib.parse import urlparse, parse_qs
from pathlib import Path
from typing import Optional, Dict, Any
import aiohttp

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────
WS_PORT      = int(os.getenv("GA_WS_PORT", "8767"))
HTTP_PORT    = int(os.getenv("GA_HTTP_PORT", "8766"))
STT_PROVIDER = os.getenv("GA_STT_PROVIDER", "openai")  # "openai" or "local"
STT_MODEL    = os.getenv("GA_STT_MODEL", "whisper-1")
OPENAI_KEY   = os.getenv("GA_OPENAI_API_KEY") or os.getenv("NOUS_API_KEY") or os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE  = os.getenv("GA_OPENAI_BASE_URL", "https://inference-api.nousresearch.com/v1")
V9_HOST      = os.getenv("GA_V9_HOST", "127.0.0.1")

# ─────────────────────────────────────────────────────────────────────────────
# TV / ADB config (Genius TV remote control)
# ─────────────────────────────────────────────────────────────────────────────
ADB = os.getenv("GA_ADB", os.path.expanduser("~/Android/Sdk/platform-tools/adb"))
# TV map: { "name": "ip" } — the Fire TVs Jeeves can drive via ADB
TVS = {
    "tom":      "192.168.12.133",   # Tom's TV (MBP monitor, HDMI1)
    "genius":   "192.168.12.116",   # Tom's 2nd TV (Strix monitor, HDMI2, 43" Hisense)
    "theater":  "192.168.12.174",   # 65" Panasonic OLED
    "andrea":   "192.168.12.152",   # Andrea's TCL
}
# Fire TV app package names (for ADB launch)
FIRE_TV_APPS = {
    "netflix":   "com.amazon.tv.launcher",
    "prime":     "com.amazon.avod.thirdpartylauncher",
    "hbo":       "com.hbo.hbonow",
    "youtube":   "com.google.android.youtube.tv",
    "home":      "com.amazon.tv.launcher",
}

# Room config: { "ip_prefix_or_exact": "room_name", ... }
_raw_rooms = os.getenv("GA_ROOM_CONFIG", "{}")
ROOM_CONFIG: Dict[str, str] = json.loads(_raw_rooms) if _raw_rooms.startswith("{") else {}

# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────
def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

# ─────────────────────────────────────────────────────────────────────────────
# Room Detection
# ─────────────────────────────────────────────────────────────────────────────
def detect_room(path: str, remote_ip: str) -> str:
    """Determine room from URL query param or IP mapping."""
    parsed = urlparse(path)
    params = parse_qs(parsed.query)
    if "room" in params:
        return params["room"][0].lower().strip()
    for ip_prefix, room in ROOM_CONFIG.items():
        if remote_ip.startswith(ip_prefix) or remote_ip == ip_prefix:
            return room
    return "unknown"

# ─────────────────────────────────────────────────────────────────────────────
# STT (Speech-to-Text)
# ─────────────────────────────────────────────────────────────────────────────
async def transcribe_audio(audio_b64: str, format_hint: str = "webm") -> str:
    """Transcribe audio bytes to text. Returns empty string on failure."""
    
    if STT_PROVIDER == "openai":
        return await _transcribe_openai(audio_b64)
    elif STT_PROVIDER == "local":
        return await _transcribe_local(audio_b64)
    else:
        log(f"[STT] Unknown provider: {STT_PROVIDER}")
        return ""

async def _transcribe_openai(audio_b64: str) -> str:
    """Use OpenAI Whisper API (or Nous-compatible endpoint)."""
    if not OPENAI_KEY:
        log("[STT] No API key configured")
        return ""
    
    try:
        audio_bytes = base64.b64decode(audio_b64)
    except Exception as e:
        log(f"[STT] Base64 decode failed: {e}")
        return ""
    
    # Write to temp file
    suffix = ".webm"  # whisper-1 accepts many formats
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name
    
    try:
        import aiohttp
        data = aiohttp.FormData()
        data.add_field("file", open(tmp_path, "rb"), filename=f"audio{suffix}")
        data.add_field("model", STT_MODEL)
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{OPENAI_BASE}/audio/transcriptions",
                headers={"Authorization": f"Bearer {OPENAI_KEY}"},
                data=data,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    text = result.get("text", "").strip()
                    log(f"[STT] Transcribed: {text[:60]}")
                    return text
                else:
                    body = await resp.text()
                    log(f"[STT] HTTP {resp.status}: {body[:200]}")
                    return ""
    except Exception as e:
        log(f"[STT] OpenAI error: {e}")
        return ""
    finally:
        try: os.unlink(tmp_path)
        except: pass

async def _transcribe_local(audio_b64: str) -> str:
    """Use local whisper.cpp (requires whisper.cpp built and model downloaded)."""
    # Placeholder — implement when whisper.cpp is installed
    log("[STT] Local STT not yet implemented")
    return ""

# ─────────────────────────────────────────────────────────────────────────────
# V9 Server Proxy (HTTP POST /chat)
# ─────────────────────────────────────────────────────────────────────────────
async def query_v9(text: str, room: str, user: str = "tom") -> dict:
    """Send text to V9 server /chat and return response dict."""
    url = f"http://{V9_HOST}:{HTTP_PORT}/chat"
    payload = {
        "text": text,
        "room": room,
        "user": user,
        "source": "room-terminal",
        "timestamp": time.time()
    }
    
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=60)
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    body = await resp.text()
                    log(f"[V9] HTTP {resp.status}: {body[:200]}")
                    return {"text": "I'm having trouble connecting right now.", "error": True}
    except Exception as e:
        log(f"[V9] Error: {e}")
        return {"text": "The server seems to be unreachable.", "error": True}

async def query_bot(text: str, room: str, user: str = "tom") -> dict:
    """Send text to the Jeeves bot via V9 /bot endpoint and return response."""
    url = f"http://{V9_HOST}:{HTTP_PORT}/bot"
    payload = {
        "text": text,
        "room": room,
        "user": user,
        "source": "room-terminal",
        "timestamp": time.time()
    }
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=120)
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    body = await resp.text()
                    log(f"[Bot] HTTP {resp.status}: {body[:200]}")
                    return {"text": "I'm having trouble reaching Jeeves right now.", "error": True}
    except Exception as e:
        log(f"[Bot] Error: {e}")
        return {"text": "Jeeves seems to be unreachable.", "error": True}

# ─────────────────────────────────────────────────────────────────────────────
# ADB / TV control helpers
# ─────────────────────────────────────────────────────────────────────────────
def _adb(serial: str, *args) -> str:
    """Run an adb command against a TV serial (ip:port). Returns stdout."""
    try:
        r = subprocess.run(
            [ADB, "-s", serial] + list(args),
            capture_output=True, text=True, timeout=15,
        )
        return (r.stdout or "").strip()
    except Exception as e:
        log(f"[ADB] error {serial} {args}: {e}")
        return ""

def adb_connect(serial: str) -> bool:
    """Ensure the TV is connected; returns True if authorized."""
    _adb(serial, "connect", serial)
    out = _adb(serial, "get-state")
    return out == "device"

def adb_launch_app(serial: str, pkg: str) -> str:
    """Launch an app on the TV via monkey (works on Fire TV)."""
    return _adb(serial, "shell", "monkey", "-p", pkg, "-c", "android.intent.category.LAUNCHER", "1")

def adb_key(serial: str, keycode: str) -> str:
    """Send a key event (e.g. KEYCODE_HOME, KEYCODE_DPAD_UP)."""
    return _adb(serial, "shell", "input", "keyevent", keycode)

def adb_switch_input(serial: str, hdmi: str) -> str:
    """Switch the TV to an HDMI input (Fire TV: via input source intent)."""
    # Fire TV: switch to HDMI via the input source picker
    return _adb(serial, "shell", "am", "start", "-a", "android.intent.action.VIEW",
                "-d", f"tvinput://hdmi{hdmi}")

def handle_command(connection, msg, room, user):
    """Handle a 'command' message from the remote: mute/wake/switch/volume/tv."""
    cmd = msg.get("command", "").lower()
    target = msg.get("target", "genius")  # which TV
    serial = TVS.get(target, TVS["genius"])
    log(f"[CMD] {room}: {cmd} target={target}")

    async def _send(payload):
        await connection.send(json.dumps(payload))

    async def _run():
        if cmd == "mute":
            # Stop Jeeves' in-flight TTS (import linux_client for stop_audio)
            try:
                import linux_client as lc
                lc.stop_audio()
                await _send({"type": "ack", "text": "Muted, sir.", "room": room})
            except Exception as e:
                await _send({"type": "error", "message": f"mute failed: {e}", "room": room})

        elif cmd == "wake":
            # Trigger a wake (e.g. show ambient / bring Jeeves to attention)
            await _send({"type": "ack", "text": "At your service, sir.", "room": room})

        elif cmd == "switch_ambient":
            # Switch the Genius TV back to Strix's ambient display (HDMI2)
            adb_switch_input(serial, "2")
            await _send({"type": "ack", "text": "Returning to the room, sir.", "room": room})

        elif cmd == "switch_tv":
            # Switch the Genius TV to its native Fire TV UI (HDMI passthrough off)
            adb_key(serial, "KEYCODE_HOME")
            await _send({"type": "ack", "text": "Switching to the TV, sir.", "room": room})

        elif cmd == "launch":
            # Launch a streaming app on the target TV
            app = msg.get("app", "").lower()
            pkg = FIRE_TV_APPS.get(app)
            if not pkg:
                await _send({"type": "error", "message": f"Unknown app: {app}", "room": room})
                return
            adb_launch_app(serial, pkg)
            await _send({"type": "ack", "text": f"Launching {app} on {target}, sir.", "room": room})

        elif cmd == "volume":
            # Volume up/down/mute on the TV
            direction = msg.get("direction", "up")
            key = {"up": "KEYCODE_VOLUME_UP", "down": "KEYCODE_VOLUME_DOWN",
                   "mute": "KEYCODE_VOLUME_MUTE"}.get(direction, "KEYCODE_VOLUME_UP")
            adb_key(serial, key)
            await _send({"type": "ack", "text": f"Volume {direction}, sir.", "room": room})

        elif cmd == "status":
            # Report Jeeves + TV status
            await _send({"type": "status", "room": room,
                         "tv": target, "connected": adb_connect(serial)})

        else:
            await _send({"type": "error", "message": f"Unknown command: {cmd}", "room": room})

    asyncio.create_task(_run())


# ─────────────────────────────────────────────────────────────────────────────
# WebSocket Handler
# ─────────────────────────────────────────────────────────────────────────────
async def handle_terminal(connection):
    """Main handler for each room terminal connection."""
    # websockets 14.x: connection.request.path for the URL path
    path = getattr(getattr(connection, 'request', None), 'path', '/')
    remote_ip = connection.remote_address[0] if connection.remote_address else "unknown"
    room = detect_room(path, remote_ip)
    user = parse_qs(urlparse(path).query).get("user", ["tom"])[0]
    
    log(f"[CONN] Room terminal connected: {room} from {remote_ip}")
    
    # Send welcome
    await connection.send(json.dumps({
        "type": "welcome",
        "room": room,
        "user": user,
        "timestamp": time.time()
    }))
    
    try:
        async for message in connection:
            try:
                msg = json.loads(message)
            except json.JSONDecodeError:
                # Binary audio or malformed JSON — skip for now
                log(f"[WARN] Non-JSON message from {room}")
                continue
            
            msg_type = msg.get("type", "")
            
            if msg_type == "register":
                # Client re-registering with metadata
                log(f"[REG] {room} registered")
                await connection.send(json.dumps({
                    "type": "ack",
                    "text": "Very good, sir. Room terminal is ready.",
                    "room": room
                }))
            
            elif msg_type == "audio":
                # Room terminal sent audio — transcribe -> V9 -> respond
                audio_b64 = msg.get("audio_b64", "")
                if not audio_b64:
                    log(f"[WARN] Empty audio from {room}")
                    continue
                
                log(f"[AUDIO] Received {len(audio_b64)} bytes from {room}")
                
                # 1. Send "thinking" status
                await connection.send(json.dumps({
                    "type": "ack",
                    "text": "One moment, sir...",
                    "room": room
                }))
                
                # 2. Transcribe
                transcript = await transcribe_audio(audio_b64, msg.get("format", "webm"))
                
                if not transcript:
                    log(f"[STT] No transcript from {room}")
                    await connection.send(json.dumps({
                        "type": "error",
                        "message": "I didn't catch that. Could you repeat?",
                        "room": room
                    }))
                    continue
                
                # 3. Show transcript to user
                await connection.send(json.dumps({
                    "type": "transcript",
                    "text": transcript,
                    "room": room
                }))
                
                # 4. Query the Jeeves bot (delegates to Hermes profile)
                log(f"[CHAT] {room}: {transcript[:60]}")
                v9_response = await query_bot(transcript, room, user)
                
                # 5. Send text response
                response_text = v9_response.get("text", "I'm not sure how to respond.")
                await connection.send(json.dumps({
                    "type": "response",
                    "text": response_text,
                    "room": room
                }))
                
                # 6. Send TTS audio if present
                audio_b64_response = v9_response.get("audio")
                if audio_b64_response:
                    await connection.send(json.dumps({
                        "type": "tts_audio",
                        "audio_b64": audio_b64_response,
                        "room": room
                    }))
                
                # 7. Turn complete
                await connection.send(json.dumps({
                    "type": "turn_end",
                    "room": room
                }))
                
                log(f"[DONE] Turn complete for {room}")
            
            elif msg_type == "text":
                # Direct text message (typing fallback) — route to Jeeves bot
                text = msg.get("text", "")
                log(f"[TEXT] {room}: {text[:60]}")
                v9_response = await query_bot(text, room, user)
                response_text = v9_response.get("text", "")
                await connection.send(json.dumps({
                    "type": "response",
                    "text": response_text,
                    "room": room
                }))
                if v9_response.get("audio"):
                    await connection.send(json.dumps({
                        "type": "tts_audio",
                        "audio_b64": v9_response["audio"],
                        "room": room
                    }))
                await connection.send(json.dumps({"type": "turn_end", "room": room}))
            
            elif msg_type == "command":
                # Remote control command (mute/wake/switch/volume/tv)
                handle_command(connection, msg, room, user)
            
            else:
                log(f"[WARN] Unknown message type: {msg_type}")
    
    except websockets.exceptions.ConnectionClosed:
        log(f"[DISC] Room terminal disconnected: {room}")
    except Exception as e:
        log(f"[ERROR] Handler exception for {room}: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
async def main():
    log("=" * 50)
    log("GeezerAid Room Terminal WebSocket Server")
    log(f"WebSocket port: {WS_PORT}")
    log(f"V9 HTTP proxy:  http://{V9_HOST}:{HTTP_PORT}")
    log(f"STT provider:   {STT_PROVIDER}")
    log(f"Room config:    {ROOM_CONFIG}")
    log("=" * 50)
    
    # Start WebSocket server
    ws_server = await websockets.serve(
        handle_terminal,
        "0.0.0.0",
        WS_PORT,
        # Allow connections from any origin (Tailscale/LAN IPs)
        origins=None,
    )
    
    log(f"[READY] WebSocket server listening on ws://0.0.0.0:{WS_PORT}")
    log("[READY] Room terminals can connect now")
    
    await asyncio.Future()  # Run forever

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("[SHUTDOWN] Room terminal server stopped")
