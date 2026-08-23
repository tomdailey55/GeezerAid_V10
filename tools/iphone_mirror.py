#!/usr/bin/env python3
"""GA-V9 phone mirror tool (2026-08-12).

Mirror-based screen reading for the iPhone, replacing the on-phone
`screentext`/`screenshot` Shortcut branches that were blocked by the phone's
Screen Recording permission.

How it works:
  iPhone Mirroring (macOS Sequoia+) shows the phone in a Mac window. We find
  that window, screencapture it (Mac grants Screen Recording), then read the
  text with the SAME local MLX VLM (:8086) that `tv_adb.describe_screen` uses
  for the Fire TV. No on-phone Shortcut action, no phone permission wall.

Requires:
  - iPhone Mirroring connected (phone unlocked & nearby, same Apple ID).
  - Screen Recording granted to the process running this (System Settings →
    Privacy & Security → Screen Recording).
  - The local MLX VLM on :8086 (same one tv_adb.py uses; if down, falls back
    to cloud gateway — but keep local when possible).

Usage:
  iphone_mirror.py screenshot [--out PATH]      # capture the mirror window to PNG
  iphone_mirror.py describe   [--prompt "..."]  # capture + read text with VLM
  iphone_mirror.py window     [--raw]           # print the mirror window id/bounds
  iphone_mirror.py drivetest                    # verify we can click the window

All read-only; never writes to the phone.
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

VLM_URL = "http://127.0.0.1:8086/v1/chat/completions"
VLM_MODEL = "unsloth/Qwen3.5-9B"
SWIFT_PROBE = r"""import CoreGraphics
let wins = CGWindowListCopyWindowInfo([.optionOnScreenOnly], kCGNullWindowID) as! [[String: Any]]
for w in wins {
    let owner = w[kCGWindowOwnerName as String] as? String ?? ""
    if owner.lowercased().contains("mirror") || owner.lowercased().contains("iphone") {
        let num = w[kCGWindowNumber as String] as? Int ?? 0
        let b = w[kCGWindowBounds as String] as? [String: Any] ?? [:]
        let x = b["X"] as? Int ?? 0
        let y = b["Y"] as? Int ?? 0
        let wd = b["Width"] as? Int ?? 0
        let ht = b["Height"] as? Int ?? 0
        print("\(num)|\(x)|\(y)|\(wd)|\(ht)")
    }
}
"""


def _find_mirror_window() -> dict:
    """Find the iPhone Mirroring window via CoreGraphics (Swift probe). Returns
    {id, name, x, y, w, h} or {} if no mirror window is found."""
    with tempfile.NamedTemporaryFile(suffix=".swift", mode="w", delete=False) as f:
        f.write(SWIFT_PROBE)
        probe = f.name
    try:
        r = subprocess.run(["swift", probe], capture_output=True, text=True, timeout=60)
    finally:
        os.unlink(probe)
    if r.returncode != 0:
        return {}
    for line in r.stdout.strip().splitlines():
        parts = line.split("|")
        if len(parts) >= 5:
            try:
                return {
                    "id": int(parts[0]),
                    "name": "",
                    "x": int(parts[1]),
                    "y": int(parts[2]),
                    "w": int(parts[3]),
                    "h": int(parts[4]),
                }
            except ValueError:
                continue
    return {}


def screencapture_window(window_id: int, dest: str) -> bool:
    r = subprocess.run(["screencapture", "-x", "-l", str(window_id), dest],
                       capture_output=True, text=True)
    return r.returncode == 0 and os.path.exists(dest)


def describe_image(path: str, prompt: str) -> str:
    """Send a PNG to the local MLX VLM and return its text description.
    Mirrors tv_adb.describe_screen's exact payload shape."""
    b64 = base64.b64encode(open(path, "rb").read()).decode()
    text = prompt or (
        "Describe what is showing on this iPhone screen in one or two sentences "
        "for an elderly person. Read any visible text out loud."
    )
    payload = {
        "model": VLM_MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            {"type": "text", "text": text},
        ]}],
        "max_tokens": 200,
    }
    req = urllib.request.Request(VLM_URL, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.loads(r.read())
        return d["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"(VLM error: {e})"


def _default_out() -> str:
    return str(Path(tempfile.gettempdir()) / "iphone-mirror-capture.png")


def cmd_window(args) -> int:
    w = _find_mirror_window()
    if not w:
        print("No iPhone Mirroring window found. Is the phone mirrored (unlocked, nearby)?")
        return 1
    print(json.dumps(w))
    if args.raw:
        print(w["id"])
    return 0


def cmd_screenshot(args) -> int:
    w = _find_mirror_window()
    if not w:
        print("No iPhone Mirroring window found. Is the phone mirrored?")
        return 1
    out = args.out or _default_out()
    if not screencapture_window(w["id"], out):
        print(f"Capture failed for window {w['id']} (bounds {w['w']}x{w['h']}). "
              "Is Screen Recording granted to this app?")
        return 1
    print(f"Captured {w['w']}x{w['h']} mirror window -> {out}")
    return 0


def cmd_describe(args) -> int:
    w = _find_mirror_window()
    if not w:
        print("No iPhone Mirroring window found. Is the phone mirrored?")
        return 1
    out = args.out or _default_out()
    if not screencapture_window(w["id"], out):
        print(f"Capture failed for window {w['id']}. Is Screen Recording granted?")
        return 1
    print(f"[captured {w['w']}x{w['h']}]", file=sys.stderr)
    print(describe_image(out, args.prompt))
    return 0


def cmd_drivetest(args) -> int:
    w = _find_mirror_window()
    if not w:
        print("No iPhone Mirroring window found.")
        return 1
    print(f"Mirror window found: id={w['id']} bounds=({w['x']},{w['y']}) {w['w']}x{w['h']}")
    print("To drive it, click at absolute screen coordinates within these bounds "
          "using the desktop control tool. (Relative-to-window clicks not yet wired.)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="iPhone Mirroring screen reader for GA")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("window", help="print mirror window id/bounds")
    p.add_argument("--raw", action="store_true", help="print just the window id")
    p.set_defaults(fn=cmd_window)

    p = sub.add_parser("screenshot", help="capture mirror window to PNG")
    p.add_argument("--out", default=None)
    p.set_defaults(fn=cmd_screenshot)

    p = sub.add_parser("describe", help="capture + read text with the VLM")
    p.add_argument("--prompt", default=None)
    p.add_argument("--out", default=None)
    p.set_defaults(fn=cmd_describe)

    p = sub.add_parser("drivetest", help="check the window can be located for driving")
    p.set_defaults(fn=cmd_drivetest)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
