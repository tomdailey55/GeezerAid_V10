#!/usr/bin/env python3
"""Genius TV — Chrome ambient display server.

Serves the GTV Chrome page on :8771 so Chrome renders it as HTML
(not as file:// which Chrome treats as plain text in --app mode).
Art rotation, clock, and weather are client-side (JS).
"""
import http.server
import os
import socketserver
import threading
import urllib.request
import urllib.parse
import json
from pathlib import Path

GTV_DIR = Path(__file__).resolve().parent.parent / "gtv_chrome"
PORT = 8771


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
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(GTV_DIR), **kwargs)

    def do_GET(self):
        if self.path == "/api/weather":
            summary, detail = fetch_weather()
            data = {"summary": summary or "—", "detail": detail or "unavailable"}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
        elif self.path == "/api/quit":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode())
            # Schedule Chrome kill after response
            threading.Thread(target=self._kill_chrome, daemon=True).start()
        elif self.path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "service": "gtv-chrome"}).encode())
        else:
            super().do_GET()
    
    def _kill_chrome(self):
        """Kill the Chrome process after a brief delay."""
        time.sleep(0.5)
        os.system("pkill -f 'chrome.*8771' 2>/dev/null")
        os.system("pkill -f 'chrome.*gtv-chrome' 2>/dev/null")

    def log_message(self, format, *args):
        pass  # silence request logs


def start_server():
    """Start the GTV HTTP server."""
    os.chdir(GTV_DIR)
    with socketserver.TCPServer(("", PORT), GTVHandler) as httpd:
        print(f"Genius TV Chrome server on http://localhost:{PORT}")
        httpd.serve_forever()


if __name__ == "__main__":
    start_server()
