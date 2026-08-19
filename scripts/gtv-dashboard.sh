#!/usr/bin/env bash
# gtv-dashboard.sh — show/hide the Chrome-hosted Genius TV dashboard.
#
# The dashboard REPLACES the QML ambient window while active (user decision),
# then the QML screensaver returns when the dashboard is dismissed.
#
#   gtv-dashboard.sh show     # stop QML ambient, open Chrome kiosk dashboard
#   gtv-dashboard.sh hide     # close Chrome, bring QML ambient back
#   gtv-dashboard.sh app URL  # open a positioned --app window (DRM services)
#
# Wayland notes (verified on this box):
#   * Chrome MUST use --ozone-platform=wayland; X11 fails "Missing $DISPLAY".
#   * wmctrl/xdotool CANNOT reposition windows under GNOME Wayland, so window
#     geometry is set at LAUNCH time via --window-size/--window-position.
set -uo pipefail

DASH_URL="${GTV_DASH_URL:-http://127.0.0.1:8770/index.html}"
PROFILE="${GTV_CHROME_PROFILE:-$HOME/.config/gtv-chrome}"
GA_DIR="$HOME/mbp-public/GA-V9"
VENV="$GA_DIR/.venv_gui/bin/python"

# Living-room legibility. The dashboard CSS was authored against 1080p, so on a
# 4K panel every dimension renders at half its intended physical size — which is
# unreadable from a sofa. Chrome's device-scale-factor scales CSS pixels up
# without touching the stylesheet.
#
# Detected automatically so the same script works on the 1080p Hisense and the
# 4K Panasonic OLED without editing. Override with GTV_SCALE if a panel needs
# a different value (e.g. a very close-viewed screen).
detect_scale() {
  if [ -n "${GTV_SCALE:-}" ]; then echo "$GTV_SCALE"; return; fi
  local w
  w=$(head -1 /sys/class/drm/card1-HDMI-A-1/modes 2>/dev/null | cut -dx -f1)
  case "${w:-1920}" in
    3840|4096) echo 2.0 ;;   # 4K  -> treat as 1920 logical
    2560)      echo 1.5 ;;   # 1440p
    *)         echo 1.0 ;;   # 1080p and below
  esac
}
SCALE="$(detect_scale)"

export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
unset DISPLAY

chrome_common=(
  --ozone-platform=wayland
  --user-data-dir="$PROFILE"
  --no-first-run
  --no-default-browser-check
  --disable-features=TranslateUI
  --autoplay-policy=no-user-gesture-required
  --force-device-scale-factor="$SCALE"
)

case "${1:-show}" in
  show)
    # 1. Stand down the QML ambient layer (dashboard replaces it).
    systemctl --user stop jeeves-gtv 2>/dev/null || true
    pkill -f 'jeeves_speaker.py' 2>/dev/null || true
    sleep 1

    # 2. Confirm the dashboard server is up before showing a blank window.
    if ! curl -sf -m 5 "${DASH_URL%/index.html}/api/health" >/dev/null; then
      echo "dashboard server not responding — starting it"
      systemd-run --user --unit=gtv-dash --working-directory="$GA_DIR" \
        /usr/bin/python3 gtv_dashboard_server.py >/dev/null 2>&1 || true
      sleep 3
    fi

    # 3. Kiosk-fullscreen Chrome = the dashboard.
    #    Anchored pattern: must not match the streaming app profile.
    pkill -f -- "--kiosk --app=$DASH_URL" 2>/dev/null || true
    sleep 1
    nohup google-chrome "${chrome_common[@]}" \
      --kiosk --app="$DASH_URL" \
      >/tmp/gtv-dashboard.log 2>&1 &
    echo "dashboard shown"
    ;;

  hide)
    # Close ONLY the kiosk dashboard window. The pattern must be anchored so
    # it cannot also match the streaming app profile (gtv-chrome-app), whose
    # windows hold the user's service logins and must never be killed here.
    pkill -f "user-data-dir=$PROFILE " 2>/dev/null || \
      pkill -f "user-data-dir=$PROFILE$" 2>/dev/null || true
    pkill -f -- "--kiosk --app=$DASH_URL" 2>/dev/null || true
    sleep 1
    # Bring the ambient screensaver back.
    rm -f "$GA_DIR/.jeeves_mic.lock"
    systemd-run --user --unit=jeeves-gtv --working-directory="$GA_DIR" \
      "$VENV" jeeves_speaker.py --gui --genius-tv >/dev/null 2>&1 || true
    echo "ambient restored"
    ;;

  app)
    # A positioned app window — used for DRM services (Netflix/HBO/Prime),
    # which cannot be composited into a dashboard tile but DO play fine in
    # their own resizable Chrome window with mouse/keyboard control.
    url="${2:?usage: gtv-dashboard.sh app URL [WxH] [X,Y]}"
    size="${3:-1280x720}"
    pos="${4:-320,180}"
    nohup google-chrome "${chrome_common[@]}" \
      --app="$url" \
      --window-size="${size/x/,}" \
      --window-position="$pos" \
      >/tmp/gtv-app.log 2>&1 &
    echo "app window: $url ($size at $pos)"
    ;;

  signin)
    # One-time sign-in to a streaming service, in a FULL browser window
    # (address bar + back button) against the persistent app profile.
    svc="${2:?usage: gtv-dashboard.sh signin netflix|hbo|prime|hulu|disney|paramount|peacock|apple}"
    curl -sf -m 10 -X POST "${DASH_URL%/index.html}/api/command" \
      -H 'Content-Type: application/json' \
      -d "{\"type\":\"signin\",\"service\":\"$svc\"}" || \
      echo "dashboard server not reachable"
    echo ""
    echo "Sign in with mouse + keyboard. The login is remembered;"
    echo "nothing will close the window automatically."
    ;;

  status)
    echo "panel:            $(head -1 /sys/class/drm/card1-HDMI-A-1/modes 2>/dev/null || echo unknown) (scale $SCALE)"
    echo -n "dashboard server: "
    curl -sf -m 4 "${DASH_URL%/index.html}/api/health" || echo "down"
    echo -n "chrome dashboard: "
    pgrep -f "user-data-dir=$PROFILE" >/dev/null && echo "running" || echo "not running"
    echo -n "qml ambient:      "
    pgrep -f 'jeeves_speaker.py' >/dev/null && echo "running" || echo "not running"
    ;;

  *)
    echo "usage: gtv-dashboard.sh {show|hide|app URL [WxH] [X,Y]|status}"
    exit 1
    ;;
esac
