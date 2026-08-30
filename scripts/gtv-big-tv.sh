#!/bin/bash
# Launch the Genius TV ambient display on the BIG TV (HDMI-A-1) via Chrome.
# Uses the threaded :8771 HTTP server so the remote-control plane (tablet)
# can broadcast next/prev/volume/wake to BOTH the big TV and the tablet.
#
# Usage: ./gtv-big-tv.sh        # launch (kills any prior GTV chrome)
#        ./gtv-big-tv.sh status  # is it running?
set -uo pipefail

PROFILE="${GTV_BIG_PROFILE:-$HOME/.config/gtv-big}"
URL="${GTV_BIG_URL:-http://127.0.0.1:8771/index.html}"

# --- living-room legibility: 4K panel -> scale up CSS px (from gtv-dashboard.sh)
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
# Hardware video decode via VA-API (Radeon 8060S / radeonsi). Without this Chrome
# falls back to software decode -> poor quality vs the TV's native app.
export LIBVA_DRIVER_NAME="${LIBVA_DRIVER_NAME:-radeonsi}"

case "${1:-show}" in
  show)
    pkill -f 'user-data-dir=.*gtv-big' 2>/dev/null || true
    sleep 1
    nohup google-chrome \
      --ozone-platform=wayland \
      --user-data-dir="$PROFILE" \
      --no-first-run \
      --no-default-browser-check \
      --disable-features=TranslateUI \
      --autoplay-policy=no-user-gesture-required \
      --force-device-scale-factor="$SCALE" \
      --enable-features=VaapiVideoDecoder,VaapiVideoEncoder \
      --use-gl=angle --use-angle=gl \
      --enable-gpu-rasterization \
      --ignore-gpu-blocklist \
      --kiosk --app="$URL" \
      >/tmp/gtv-big-tv.log 2>&1 &
    echo "big TV ambient shown: $URL (scale $SCALE, VA-API hw decode)"
    ;;
  close)
    pkill -f 'user-data-dir=.*gtv-big' 2>/dev/null || true
    echo "big TV chrome closed"
    ;;
  status)
    if pgrep -f 'user-data-dir=.*gtv-big' >/dev/null; then
      echo "big TV chrome: RUNNING"
    else
      echo "big TV chrome: not running"
    fi
    ;;
  *)
    echo "usage: $0 {show|close|status}"
    exit 1
    ;;
esac
