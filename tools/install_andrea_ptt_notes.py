#!/usr/bin/env python3
"""install_andrea_ptt.sh — post-install notes for Andrea's PTT voice path.

On macOS with Chrome trusted-certs done (install_andrea_kiosk.sh), the PTT
mic button on the GTV page works OUT OF THE BOX:
  - getUserMedia over HTTPS (trusted cert)
  - macOS mic permission: Chrome asks on first hold; click Allow once.
  - Reply audio plays via the built-in <Audio> element to HDMI → TV speakers.

So there is NO separate voice client to install for v1 — the tablet pattern
applies directly. This file documents the permission steps + fallbacks.

Manual steps (once, on-site):
  1. Hold the mic button on the GTV page → macOS dialog
     "'Google Chrome' would like to access the microphone" → OK
  2. First reply audio: macOS may prompt for autoplay — click Allow
     (kiosk flag --autoplay-policy already set, so unlikely)
  3. Say something: "Circe, what time is it?" → af_amy reply from TV speakers

Fallbacks:
  - If Chrome blocks mic in kiosk mode → launch with
    --use-fake-ui-for-media-stream (auto-grant) — add to plist if needed.
  - If HDMI audio routing misbehaves → set System Sound Output to the TCL/HDMI
    (amixer/switchaudio -s "TV").
  - If HTTPS trust fails → fall back to server-mic tap flow (bridge exists).
"""
print(__doc__)