#!/usr/bin/env python3
"""GA-V9 iPhone CoreDevice tool (2026-08-12).

Device-level iPhone control via pymobiledevice3's reverse-engineered CoreDevice
protocol — the robust backend for "make it happen" (Jeeves sees + acts on the
phone). This is the ADB-for-iPhone path, NOT the Apple-blocked mirror-window
click emulation and NOT the fragile mega-shortcut.

Status (verified 2026-08-13 on iPad iOS 27.0 beta):
  - screenshot / read   -> WORKS (native full-res capture, no mirror needed)
  - swipe / drag (touch) -> VERIFIED WORKING on iOS 27 (swipe opened Spotlight
    on the iPad iOS 27 beta — genuine UIKit delivery). On iOS 26.6 the phone
    still gets CoreDeviceError 9021 "Remote control requires iOS 27.0 or later".
  - accessibility list  -> WORKS (developer accessibility list-items lists all
    on-screen elements w/ platform_identifier; no frame rects).
  - accessibility press -> BLOCKED: perform_press needs task_for_pid-allow
    entitlement; accepted but no-op on the home screen.
  - precise taps        -> FRAGILE: VLM gives unreliable icon pixel coords; the
    capture is portrait 2048x2732 while HID surface is landscape 2732x2048 (90°
    rotation). WDA (exact frames + tap-by-selector) is the RIGHT tool but needs
    a WebDriverAgentRunner installed, which requires an Xcode build against the
    iOS 27 beta — Xcode can't target the beta yet. Revisit when Xcode supports
    iOS 27.
  - HID keyboard type   -> BLOCKED: create_keyboard_service() times out over the
    tunnel (SettingsFrame handshake never completes). Separate from touch.
  - tapname             -> capture + VLM-locate app icon + tap; works only when
    the VLM's pixel coords are accurate (unreliable for small icons).

Requires:
  - Device connected via USB, unlocked, this Mac trusted.
  - Developer Mode enabled + Developer Disk Image mounted (one-time):
        export PYTHONPATH=''
        .venv-iphone-spike/bin/python -m pymobiledevice3 mounter auto-mount
  - The spike venv (Python 3.12, pymobiledevice3) at
    ~/Public/GA-V9/.venv-iphone-spike
  - The local MLX VLM on :8086 for describe/locate (same as tv_adb/iphone_mirror).

Usage:
  iphone_core.py screenshot [OUT]           # native full-res PNG capture
  iphone_core.py describe [--prompt ".."]   # capture + read text with :8086 VLM
  iphone_core.py tapname APP                # tap an app by name (VLM-located)
  iphone_core.py tap X Y                     # touch at HID coords (iOS 27+)
  iphone_core.py status                      # device + touch-capability check
  # + tools/ax_press.py list|press           # accessibility element list/press

Coordinates for tap: 0..65535 across the screen (hid_x = px_x*65535/px_w).
Read + swipe are safe; tap/type/tapname are WRITE and need iOS 27.
"""
import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VENV_PY = REPO / ".venv-iphone-spike" / "bin" / "python"
PMD = [str(VENV_PY), "-m", "pymobiledevice3"]

VLM_URL = "http://127.0.0.1:8086/v1/chat/completions"
VLM_MODEL = "unsloth/Qwen3.5-9B"


def _pmd(args, timeout=180):
    """Run a pymobiledevice3 subcommand with the venv and a clean PYTHONPATH
    (the hermes venv leaks broken 3.11 packages into the 3.12 spike venv)."""
    env = dict(os.environ)
    env["PYTHONPATH"] = ""
    r = subprocess.run(PMD + args, capture_output=True, text=True, timeout=timeout, env=env)
    return r


def _first_device() -> str:
    """Return the first USB-connected device's UDID, or ''."""
    r = _pmd(["usbmux", "list"])
    if r.returncode != 0:
        return ""
    m = re.search(r'"Identifier"\s*:\s*"([0-9A-Fa-f-]+)"', r.stdout)
    return m.group(1) if m else ""


def _describe(path: str, prompt: str) -> str:
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
            return json.loads(r.read())["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"(VLM error: {e})"


def cmd_screenshot(args) -> int:
    out = args.out or "/tmp/iphone-core.png"
    r = _pmd(["developer", "core-device", "screen-capture", "screenshot", out, "--userspace"])
    print(r.stdout.strip() or r.stderr.strip())
    if r.returncode == 0 and os.path.exists(out):
        print(f"Screenshot -> {out}")
        return 0
    print("Screenshot FAILED. Is the phone USB-connected, unlocked, DDI mounted?")
    return 1


def cmd_describe(args) -> int:
    out = args.out or "/tmp/iphone-core.png"
    r = _pmd(["developer", "core-device", "screen-capture", "screenshot", out, "--userspace"])
    if r.returncode != 0 or not os.path.exists(out):
        print(r.stdout.strip() or r.stderr.strip())
        print("Capture FAILED. Is the phone USB-connected, unlocked, DDI mounted?")
        return 1
    print("[captured]", file=sys.stderr)
    print(_describe(out, args.prompt))
    return 0


def _locate_px(path: str, app: str) -> tuple | None:
    """Ask the local VLM where `app`'s icon is on the screenshot (pixel px,py).
    Returns (px_x, px_y) or None if not found / unparseable."""
    b64 = base64.b64encode(open(path, "rb").read()).decode()
    prompt = (
        f"Look at this screen image. Find the '{app}' app icon. "
        f"Reply ONLY with its center as two integers: 'X Y' in pixels. "
        f"If it is not visible, reply exactly 'not found'."
    )
    payload = {
        "model": VLM_MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            {"type": "text", "text": prompt},
        ]}],
        "max_tokens": 30,
    }
    req = urllib.request.Request(VLM_URL, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            resp = json.loads(r.read())["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"(locate error: {e})")
        return None
    if not resp or "not found" in resp.lower():
        return None
    m = re.search(r"(-?\d+)\s*[,x\s]\s*(-?\d+)", resp)
    if not m:
        print(f"(unparseable locate response: {resp!r})")
        return None
    return int(m.group(1)), int(m.group(2))


def _screen_px(path: str) -> tuple:
    """Read pixel width/height from the PNG via sips. Fallback 2048x2732."""
    try:
        out = subprocess.run(["/usr/bin/sips", "-g", "pixelWidth", "-g", "pixelHeight", path],
                             capture_output=True, text=True, timeout=10)
        w = int(re.search(r"pixelWidth:\s*(\d+)", out.stdout).group(1))
        h = int(re.search(r"pixelHeight:\s*(\d+)", out.stdout).group(1))
        return w, h
    except Exception:
        return 2048, 2732


def _hid_surface_dims() -> tuple:
    """Return (w, h) of displays[0].currentMode.size — the space the HID
    digitizer maps 0..65535 across. Falls back to the capture dims."""
    r = _pmd(["developer", "core-device", "get-display-info", "--userspace"])
    try:
        data = json.loads(r.stdout)
        d0 = data.get("displays") or data.get("display") or []
        if isinstance(d0, list):
            d0 = d0[0] if d0 else {}
        size = (d0.get("currentMode") or {}).get("size") or []
        if len(size) >= 2 and size[0] and size[1]:
            return int(size[0]), int(size[1])
    except Exception:
        pass
    return None


def _px_to_hid(px_x, px_y, cap_w, cap_h, hid_w, hid_h):
    """Convert screenshot-pixel (px_x,px_y) in a cap_w×cap_h capture to HID
    coords over a hid_w×hid_h surface. If the capture is rotated 90° relative
    to the HID surface (dims swapped, e.g. portrait capture vs landscape HID),
    apply the rotation so the tap lands correctly."""
    if (cap_w == hid_h and cap_h == hid_w):
        # 90° rotation (portrait capture of a landscape surface, or vice versa).
        # Center must map to center. hid_x runs along capture's y; hid_y along x.
        # Try: hid_y flipped to account for mirrored rotation.
        hid_x = round(px_y * 65535 / cap_h)
        hid_y = round((cap_w - px_x) * 65535 / cap_w)
        return hid_x, hid_y
    # No rotation (dims agree).
    hid_x = round(px_x * 65535 / cap_w)
    hid_y = round(px_y * 65535 / cap_h)
    return hid_x, hid_y


def cmd_tapname(args) -> int:
    """Tap an app by NAME: capture, VLM-locate its icon center, convert px->HID
    (orientation-aware), then tap. Removes hand-guessed coordinates."""
    out = args.out or "/tmp/iphone-core.png"
    r = _pmd(["developer", "core-device", "screen-capture", "screenshot", out, "--userspace"])
    if r.returncode != 0 or not os.path.exists(out):
        print("Capture FAILED. Is the device USB-connected, unlocked, DDI mounted?")
        return 1
    loc = _locate_px(out, args.app)
    if not loc:
        print(f"'{args.app}' not found on screen (is it visible?).")
        return 1
    px_x, px_y = loc
    cap_w, cap_h = _screen_px(out)
    hid_dims = _hid_surface_dims()
    if hid_dims:
        hid_w, hid_h = hid_dims
    else:
        hid_w, hid_h = cap_w, cap_h  # fallback: assume no rotation
    hid_x, hid_y = _px_to_hid(px_x, px_y, cap_w, cap_h, hid_w, hid_h)
    print(f"located '{args.app}' at px ({px_x},{px_y}); capture {cap_w}x{cap_h}; "
          f"HID surface {hid_w}x{hid_h}; tap ({hid_x},{hid_y})")
    r2 = _pmd(["developer", "core-device", "universal-hid-service", "tap",
               str(hid_x), str(hid_y), "--userspace"])
    print(r2.stdout.strip() or r2.stderr.strip())
    if r2.returncode != 0:
        print("tap FAILED. Likely iOS 26.6: 'Remote control requires iOS 27.0'.")
        return 1
    print(f"tap '{args.app}' sent")
    return 0


def cmd_tap(args) -> int:
    r = _pmd(["developer", "core-device", "universal-hid-service", "tap",
              str(args.x), str(args.y), "--userspace"])
    print(r.stdout.strip() or r.stderr.strip())
    if r.returncode != 0:
        print("tap FAILED. Likely iOS 26.6: 'Remote control requires iOS 27.0'.")
        return 1
    print(f"tap ({args.x},{args.y}) sent")
    return 0


def cmd_type(args) -> int:
    r = _pmd(["developer", "core-device", "universal-hid-service", "keyboard",
              "type", args.text, "--userspace"])
    print(r.stdout.strip() or r.stderr.strip())
    if r.returncode != 0:
        print("type FAILED. Likely iOS 26.6: 'Remote control requires iOS 27.0'.")
        return 1
    print(f"typed: {args.text!r}")
    return 0


def cmd_status(args) -> int:
    dev = _first_device()
    if not dev:
        print("No USB device detected. Plug in + unlock + trust the Mac.")
        return 1
    print(f"Device: {dev}")
    # Touch capability: classify by output content, not exit code
    r = _pmd(["developer", "core-device", "universal-hid-service", "tap",
              "32768", "32768", "--userspace"])
    both = r.stdout + r.stderr
    if "iOS 27.0" in both or "9021" in both:
        print("Touch: BLOCKED on this iOS (requires iOS 27.0+). "
              "Read/screenshot still work.")
        print("  (re-test on iOS 27, or on an iPad running the iOS 27 beta)")
        return 0
    if r.returncode == 0:
        print("Touch: WORKS (iOS 27+ or capability present)")
        return 0
    print("Touch: unknown error; screenshot likely still works.")
    print(both.strip()[:300])
    return 0


def _wda_tunnel_flag() -> str:
    """Return '--tunnel <udid>' for WDA commands (first USB device)."""
    import subprocess as sp
    r = sp.run([sys.executable, "-m", "pymobiledevice3", "usbmux", "list"],
               capture_output=True, text=True, timeout=30)
    m = re.search(r'"UniqueDeviceID"\s*:\s*"([0-9A-F-]+)"', r.stdout)
    return f"--tunnel {m.group(1)}" if m else ""


def _wda(fn_args, timeout=60):
    """Run a WDA subcommand via the NO-ROOT direct path (no sudo tunneld).
    Maps list-items/tap/press to wda_direct.py. Returns exit code."""
    import subprocess as sp
    # translate CLI-style args to wda_direct.py
    op = fn_args[0]
    direct_args = []
    if op == "list-items":
        direct_args = ["list"]
    elif op == "tap":
        # fn_args: ["tap", selector, "--using", using]
        sel = fn_args[1]
        using = "name"
        if "--using" in fn_args:
            using = fn_args[fn_args.index("--using")+1]
        direct_args = ["tap", sel, "--using", using]
    elif op == "press":
        direct_args = ["press"] + fn_args[1:]
    elif op == "open":
        direct_args = ["open"] + fn_args[1:]
    else:
        direct_args = [op] + fn_args[1:]
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wda_direct.py")
    cmd = [sys.executable, script] + direct_args
    r = sp.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.stdout.strip(): print(r.stdout.strip())
    if r.returncode:
        print(r.stderr.strip(), file=sys.stderr)
        return r.returncode
    return 0


def cmd_wdalist(args) -> int:
    """WDA element tree (exact frames + names). Requires tunneld + WDA test running."""
    return _wda(["list-items"], timeout=60)


def cmd_wdatap(args) -> int:
    """WDA tap an element by name. Requires tunneld + WDA test running."""
    return _wda(["tap", args.selector, "--using", args.using], timeout=40)


def cmd_wdapress(args) -> int:
    """WDA press device buttons (home, volumeup, volumedown, lock)."""
    return _wda(["press", args.names], timeout=40)


def cmd_wdaopen(args) -> int:
    """WDA open an app by name (visible-icon class chain, excludes widgets)."""
    return _wda(["open", args.app], timeout=50)


def cmd_wdatree(args) -> int:
    """WDA element tree WITH frames (name + x/y/w/h + type).
    Uses get_source XML; frames are reliable for an open app's UI but report
    0,0 for home-screen icons. Requires tunneld + WDA test running."""
    # Reuse the spike venv's python (has pymobiledevice3) to run wda_frames.py
    import os as _os
    py = _os.path.expanduser("~/Public/GA-V9/.venv-iphone-spike/bin/python")
    script = _os.path.join(_os.path.dirname(__file__), "wda_frames.py")
    import subprocess as sp
    r = sp.run([py, script], capture_output=True, text=True, timeout=90)
    if r.stdout.strip(): print(r.stdout.strip())
    if r.stderr.strip(): print(r.stderr.strip(), file=sys.stderr)
    return r.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description="iPhone CoreDevice control for GA")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("screenshot", help="native full-res capture")
    p.add_argument("out", nargs="?", default=None)
    p.set_defaults(fn=cmd_screenshot)

    p = sub.add_parser("describe", help="capture + read with the VLM")
    p.add_argument("--prompt", default=None)
    p.add_argument("--out", default=None)
    p.set_defaults(fn=cmd_describe)

    p = sub.add_parser("tapname", help="tap an app by name (capture+VLM-locate+tap)")
    p.add_argument("app")
    p.add_argument("--out", default=None)
    p.set_defaults(fn=cmd_tapname)

    p = sub.add_parser("tap", help="touch at HID coords (iOS 27+ only)")
    p.add_argument("x", type=int)
    p.add_argument("y", type=int)
    p.set_defaults(fn=cmd_tap)

    p = sub.add_parser("type", help="type text (iOS 27+ only)")
    p.add_argument("text")
    p.set_defaults(fn=cmd_type)

    p = sub.add_parser("status", help="device + touch-capability check")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("wdalist", help="WDA element tree w/ exact frames (needs tunneld + WDA test)")
    p.set_defaults(fn=cmd_wdalist)

    p = sub.add_parser("wdatap", help="WDA tap element by name (needs tunneld + WDA test)")
    p.add_argument("selector")
    p.add_argument("--using", default="name", help="lookup strategy (name/label/xpath)")
    p.set_defaults(fn=cmd_wdatap)

    p = sub.add_parser("wdaopen", help="WDA open app by name (visible-icon, excludes widgets)")
    p.add_argument("app")
    p.set_defaults(fn=cmd_wdaopen)

    p = sub.add_parser("wdapress", help="WDA press device buttons (home lock volumeup ...)")
    p.add_argument("names")
    p.set_defaults(fn=cmd_wdapress)

    p = sub.add_parser("wdatree", help="WDA element tree WITH frames (name+x/y/w/h)")
    p.set_defaults(fn=cmd_wdatree)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
