# iPhone Control Spike — pymobiledevice3 core-device (2026-08-12)

**Result: SPLIT — READ works, WRITE blocked on this phone's iOS.**
- **Screenshot (read): VERIFIED WORKING** on this phone (iOS 26.6). Native 1284x2778
  capture via CoreDevice userspace tunnel, read cleanly by the VLM.
- **Touch/keyboard (write/control): BLOCKED.** CoreDevice remote control returns
  `code 9021 "Remote control requires iOS 27.0 or later on this device."`
  The phone is on **iOS 26.6**. Apple now gates touch injection behind iOS 27.0+.
- **Conclusion:** pymobiledevice3 gives a robust *screen-read* backend on iOS 26.6,
  but NOT touch control. Touch/control needs either (a) iOS 27.0+ on the phone, or
  (b) an alternative write path (tiny Shortcuts for specific actions).

**Research conclusion (verified 2026-08-12):** Clicking the iPhone Mirroring
window is Apple-blocked (KM forum: double/triple click = 100% block; StackExchange
confirms). The correct mechanism is pymobiledevice3's HID service, which sends
real `UIEventTypeTouches` over the CoreDevice tunnel — but on this device the
HID path is version-gated to iOS 27.0+.

---

## Environment (already set up)

- Venv: `~/Public/GA-V9/.venv-iphone-spike` (Python 3.12.9, pymobiledevice3 10.7.3)
- **CRITICAL PYTHONPATH GOTCHA:** The shell inherits
  `PYTHONPATH=~/.hermes/hermes-agent/...` which leaks the hermes venv's
  Python-3.11 packages (broken `cryptography`/`_cffi_backend`). ALWAYS run with
  `export PYTHONPATH=''` first. Do not create the venv on Python 3.14 (3.12 is
  stable). Do not activate the venv via `.venv-iphone-spike/bin/activate` if it
  inherits the leak — export PYTHONPATH='' instead.

## Prerequisites on the phone (done this session)

1. Phone plugged in via USB (the core-device userspace tunnel auto-establishes;
   no `sudo` needed — only the explicit `start-tunnel` CLI subcommand is sudo-gated,
   but the `developer core-device ... --userspace` commands auto-tunnel).
2. **Developer Mode** already enabled (confirmed via `amfi enable-developer-mode`).
3. **Developer Disk Image mounted** — `mounter auto-mount` succeeds ("mounted
   successfully").

## Working command sequence (VERIFIED)

From `~/Public/GA-V9`, phone plugged in + unlocked:

```bash
export PYTHONPATH=''
SPIKE=.venv-iphone-spike/bin/python -m pymobiledevice3

# 0. Device detection over USB
$SPIKE usbmux list                          # -> Tom's iPhone (iPhone14,3, iOS 26.6)

# 1. Mount DDI (one-time; already mounted this session)
$SPIKE mounter auto-mount

# 2. Screenshot — WORKS on iOS 26.6 (positional output arg; NO --out)
$SPIKE developer core-device screen-capture screenshot /tmp/iphone-spike.png --userspace

# 3. Touch — BLOCKED on iOS 26.6 (requires iOS 27.0+; code 9021)
$SPIKE developer core-device universal-hid-service tap 32768 61800 --userspace
#    -> error: "Remote control requires iOS 27.0 or later on this device."
```

## What success / failure looks like

- `usbmux list` shows the device. ✅
- Screenshot returns real pixels (1284x2778, not black). ✅ VERIFIED
- `tap` raises CoreDeviceError 9021 on iOS 26.6 — touch is version-gated. ❌
- If steps 0-1 fail: USB not detected / Developer Mode not enabled / DDI not mounted.

## Reference (from the pymobiledevice3 source, verified this session)

- `remote/core_device/hid_service.py` — HID wire formats (touch 58-byte rid=0x09,
  gesture 19-byte rid=0x13, keyboard 39-byte rid=0x01). Tap = CONTACT(0xC2)+
  RELEASE(0x02) at same (x,y). Auth gate: an active media stream (`touch_session`)
  is REQUIRED for reports to reach UIKit — and on iOS 26.6 that media-stream start
  is what rejects with 9021 (iOS 27.0+ required).
- `remote/core_device/screen_stream.py` — live video (RTP/HEVC → web viewer).
- `remote/core_device/screen_capture_service.py` — `capture_screenshot`.
- CLI: `developer core-device universal-hid-service {tap,drag,keyboard,list-connected}`,
  `developer core-device screen-capture screenshot {output}`,
  `developer core-device hid button`.

## Implications for GA / next steps

1. **Screen-read is solved on this phone** — `iphone_mirror.py` (mirror window) OR
   pymobiledevice3 native screenshot (better: full-res 1284x2778, no mirror needed).
   Prefer the CoreDevice screenshot as the capture backend when the phone is USB-
   connected; keep mirror for the "drive the visible mirror" case.
2. **Touch control needs iOS 27.0+** — plan around it:
   - If/when the phone updates to iOS 27, re-run the touch test.
   - Until then, WRITE actions on the phone must use **tiny Shortcuts** (per the
     design rule) triggered by the existing iMessage channel — not CoreDevice touch.
   - The "make it happen" general-control vision on iPhone is gated on iOS 27
     (or an alternative); don't invest further in CoreDevice touch on 26.6.

