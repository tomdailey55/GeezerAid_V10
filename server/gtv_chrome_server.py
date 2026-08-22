#!/usr/bin/env python3
"""Genius TV — Chrome ambient display server.

Serves the GTV Chrome page on :8771 so Chrome renders it as HTML
(not as file:// which Chrome treats as plain text in --app mode).
Art rotation, clock, and weather are client-side (JS).

Also exposes a remote-control plane over SSE + POST endpoints so any
client (a tablet, a future big TV) can broadcast commands to ALL
connected displays at once:

    /api/remote?action=next          advance art on every display
    /api/remote?action=prev          step art back on every display
    /api/remote?action=volume_up     raise default sink volume (HDMI TV)
    /api/remote?action=volume_down   lower default sink volume
    /api/remote?action=mute          toggle default sink mute
    /api/remote?action=wake          signal Jeeves wake state to displays
    /api/events                      SSE stream (displays subscribe here)
    /api/status                      health
    /api/weather                     wttr.in
    /api/quit                        kill the Chrome kiosk
"""
import http.server
import os
import time
import queue
import subprocess
import socketserver
import threading
import urllib.request
import urllib.parse
import json
from pathlib import Path

GTV_DIR = Path(__file__).resolve().parent.parent / "gtv_chrome"
PORT = 8771

# SSE clients subscribed to remote-command broadcasts.
_subscribers: set = set()
_sub_lock = threading.Lock()


def broadcast(payload: dict):
    """Push a JSON payload to every subscribed display (non-blocking)."""
    msg = f"data: {json.dumps(payload)}\n\n".encode()
    dead = []
    with _sub_lock:
        subs = list(_subscribers)
    for q in subs:
        try:
            q.put_nowait(msg)
        except queue.Full:
            dead.append(q)
    if dead:
        with _sub_lock:
            for q in dead:
                _subscribers.discard(q)


def _run(cmd):
    """Run a shell command silently; return (ok, text)."""
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=8)
        return p.returncode == 0, p.stdout.strip()
    except Exception as e:
        return False, str(e)


def handle_volume(action: str) -> tuple[bool, str]:
    """Change default-sink volume. Returns (ok, human message)."""
    if action == "volume_up":
        return _run("wpctl set-volume @DEFAULT_SINK@ 0.05+")
    if action == "volume_down":
        return _run("wpctl set-volume @DEFAULT_SINK@ 0.05-")
    if action == "mute":
        return _run("wpctl set-mute @DEFAULT_SINK@ toggle")
    return False, "unknown volume action"


def fetch_weather():
    """Return (summary, detail) from wttr.in JSON, or (None, None)."""
    loc = urllib.parse.quote("Sarasota,FL")
    try:
        url = f"https://wttr.in/{loc}?format=j1"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req, timeout=8) as r:
            raw = r.read().decode("utf-8", "replace")
        data = json.loads(raw)
        current = data["current_condition"][0]
        cond = current["weatherDesc"][0]["value"]
        temp = current["temp_F"]
        feels = current["FeelsLikeF"]
        hum = current["humidity"]
        summary = f"{temp}°F · {cond}"
        detail = f"Feels like {feels}°F" if feels != temp else f"Humidity {hum}%"
        return summary, detail
    except Exception:
        return None, None


class GTVHandler(http.server.SimpleHTTPRequestHandler):
    # Allow immediate rebind after a restart (avoids TIME_WAIT "Address in use").
    allow_reuse_address = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(GTV_DIR), **kwargs)

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json_remote(self, action):
        if action == "next" or action == "prev":
            broadcast({"type": "command", "action": action})
            return self._json(200, {"ok": True, "action": action, "broadcast": True})
        if action == "wake":
            broadcast({"type": "command", "action": action})
            return self._json(200, {"ok": True, "action": action, "broadcast": True})
        if action in ("volume_up", "volume_down", "mute"):
            ok, out = handle_volume(action)
            return self._json(200, {"ok": ok, "action": action, "result": out})
        return self._json(400, {"ok": False, "error": f"unknown action: {action}"})

    def do_GET(self):
        path = self.path.split("?")[0]
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)

        if path == "/api/weather":
            summary, detail = fetch_weather()
            self._json(200, {"summary": summary or "—", "detail": detail or "unavailable"})
        elif path == "/api/status":
            self._json(200, {"ok": True, "service": "gtv-chrome"})
        elif path == "/api/quit":
            self._json(200, {"ok": True})
            threading.Thread(target=self._kill_chrome, daemon=True).start()
        elif path == "/api/remote":
            action = (query.get("action") or [""])[0]
            self._json_remote(action)
        elif path == "/api/events":
            self._sse()
        else:
            super().do_GET()

    def do_POST(self):
        path = self.path.split("?")[0]
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        if path == "/api/remote":
            action = (query.get("action") or [""])[0]
            self._json_remote(action)
        else:
            self.send_response(404)
            self.end_headers()

    def _sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        q = queue.Queue(maxsize=20)
        with _sub_lock:
            _subscribers.add(q)
        try:
            # Heartbeat so proxies/clients don't drop the stream.
            while True:
                try:
                    self.wfile.write(q.get(timeout=15))
                except queue.Empty:
                    self.wfile.write(b": heartbeat\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with _sub_lock:
                _subscribers.discard(q)

    def _kill_chrome(self):
        """Kill the Chrome process after a brief delay."""
        time.sleep(0.5)
        os.system("pkill -f 'chrome.*8771' 2>/dev/null")
        os.system("pkill -f 'chrome.*gtv-chrome' 2>/dev/null")

    def log_message(self, format, *args):
        pass  # silence request logs


class ReusableThreadingServer(http.server.ThreadingHTTPServer):
    """Threaded server that rebinds immediately after restart (avoids TIME_WAIT)."""
    allow_reuse_address = True


def start_server():
    """Start the GTV HTTP server."""
    os.chdir(GTV_DIR)
    with ReusableThreadingServer(("", PORT), GTVHandler) as httpd:
        print(f"Genius TV Chrome server on http://localhost:{PORT}")
        httpd.serve_forever()


if __name__ == "__main__":
    start_server()
