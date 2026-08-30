#!/usr/bin/env python3
"""gtv_voice_bridge.py — bridges GTV display taps to Jeeves' voice loop.

Architecture (server-mic variant, matches the standing thin-client rule):
  1. A display tap sends  POST /api/remote?action=voice_tap  (chrome server).
  2. The chrome server writes the flag file  ~/.geeza/gtv_voice_tap.
  3. This bridge notices the flag, clears it, and writes the force-wake marker
     (~/.geeza/jeeves_force_wake) that jeeves_speaker.py polls in its wake loop.
  4. jeeves_speaker wakes immediately on the NEXT VAD event (the user is
     already talking), captures the query via its normal buffer, and answers
     through the GA /chat pipeline as usual (persona-aware).

Run:  python3 gtv_voice_bridge.py   (daemon; stdout logs)
"""
import os
import sys
import time

WAKE_FLAG = os.path.expanduser("~/.geeza/gtv_voice_tap")     # chrome server writes
FORCE_WAKE = os.path.expanduser("~/.geeza/jeeves_force_wake")  # jeeves reads
POLL_SEC = 0.4


def main():
    os.makedirs(os.path.dirname(WAKE_FLAG), exist_ok=True)
    print(f"[bridge] tap-watch on {WAKE_FLAG} -> {FORCE_WAKE}", flush=True)
    while True:
        try:
            if os.path.exists(WAKE_FLAG):
                os.unlink(WAKE_FLAG)
                with open(FORCE_WAKE, "w") as f:
                    f.write(str(time.time()))
                print(f"[bridge] tap -> force-wake ({time.strftime('%H:%M:%S')})", flush=True)
        except Exception as e:
            print(f"[bridge] error: {e}", file=sys.stderr, flush=True)
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()