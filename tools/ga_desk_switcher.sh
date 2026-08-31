#!/usr/bin/env bash
# ga_desk_switcher.sh — iMac-side GA-Desk switcher (runs on Andrea's iMac as
# the `ga` user, launched by install_andrea_kiosk.sh).
#
# Watches the GTV SSE plane for desk_open / desk_close and:
#   desk_open  → bring Hermes Desktop forward, fullscreen over the kiosk
#   desk_close → activate the kiosk Chrome again (art returns underneath)
#
# No wake loop, no polling of files: a single SSE connection, reconnect with
# backoff. Exit paths all funnel through desk_close (spoken, idle-timeout in
# gtv.js, or night mode) so the kiosk always wins back the screen.

STRIX="${STRIX_HOST:-100.103.195.22}"
PORT="${GTV_PORT:-8771}"

bring_desk_forward() {
  osascript >/dev/null 2>&1 <<'AS'
    tell application "System Events"
      set hermesApps to (every process whose name is "Hermes" or name is "Hermes Desktop")
      if (count of hermesApps) > 0 then
        tell frontmost of hermesApps to set frontmost to true
      else
        do shell script "open -a 'Hermes'"
      end if
      -- fullscreen it if not already
      tell process "Hermes"
        try
          set v1 to value of attribute "AXFullScreen" of window 1
          if v1 is false then set value of attribute "AXFullScreen" of window 1 to true
        end try
      end tell
    end tell
AS
}

back_to_kiosk() {
  osascript >/dev/null 2>&1 <<'AS'
    tell application "Google Chrome" to activate
AS
}

echo "[ga-desk-switcher] watching SSE at http://${STRIX}:${PORT}/api/events"

while true; do
  curl -s -N --max-time 0 "http://${STRIX}:${PORT}/api/events" 2>/dev/null | while IFS= read -r line; do
    case "$line" in
      *desk_open*)
        echo "$(date '+%H:%M:%S') desk_open → Hermes forward"
        bring_desk_forward
        ;;
      *desk_close*)
        echo "$(date '+%H:%M:%S') desk_close → kiosk back"
        back_to_kiosk
        ;;
    esac
  done
  echo "$(date '+%H:%M:%S') SSE dropped; reconnecting in 5s"
  sleep 5
done