#!/bin/bash
# Launch Genius TV Chrome ambient display
# Usage: ./launch-gtv-chrome.sh [art-dir]

ART_DIR="${1:-$HOME/genius-tv/art}"
CHROME_CMD="${CHROME_CMD:-google-chrome}"

# Kill existing GTV Chrome
pkill -f 'chrome.*gtv_chrome' 2>/dev/null || true

# Launch Chrome in kiosk mode with GTV
$CHROME_CMD \
    --kiosk \
    --app="file://$PWD/index.html" \
    --window-size=1920,1080 \
    --window-position=0,0 \
    --no-first-run \
    --disable-sync \
    --disable-notifications \
    --disable-background-networking \
    --disable-component-update \
    --disable-default-apps \
    --disable-extensions \
    --disable-features=TranslateUI \
    --disable-ipc-flooding-protection \
    --disable-renderer-backgrounding \
    --metrics-recording-only \
    --no-default-browser-check \
    --enable-features=WebUIDarkMode \
    --force-dark-mode \
    --user-data-dir="$HOME/.config/gtv-chrome" \
    --class=GTVCHROME \
    "file://$PWD/index.html" &
