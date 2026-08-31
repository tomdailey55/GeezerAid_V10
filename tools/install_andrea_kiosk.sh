#!/bin/bash
# install_andrea_kiosk.sh — run ON Andrea's iMac as user `ga` (or via SSH as ga).
# Sets up the GTV kiosk LaunchAgent pointing at Strix's GTV server.
#
# Usage: bash install_andrea_kiosk.sh [STRIX_HOST]
#   STRIX_HOST defaults to 100.103.195.22 (Strix Tailscale)

set -u
STRIX_HOST="${1:-100.103.195.22}"
GTV_URL="https://${STRIX_HOST}:8443/index.html?power=full"
PLIST_LABEL="com.ga.gtv-kiosk"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
KA_DIR="$HOME/.ga-kiosk-profile"

echo "=== 1. ensure Chrome exists ==="
if [ ! -x "$CHROME" ]; then
  echo "Chrome missing — installing via Homebrew cask..."
  brew install --cask google-chrome || { echo "INSTALL CHROME MANUALLY, then re-run"; exit 1; }
fi

echo "=== 2. trust Strix self-signed cert in Keychain (mic needs HTTPS trust) ==="
# Fetch the cert exposed by Strix and trust it for SSL.
CERT_PEM="$HOME/.ga/strix-gtv.pem"
mkdir -p "$(dirname "$CERT_PEM")"
echo | openssl s_client -connect "${STRIX_HOST}:8443" -servername gtv 2>/dev/null \
  | openssl x509 -outform pem > "$CERT_PEM"
if [ -s "$CERT_PEM" ]; then
  sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain "$CERT_PEM" \
    && echo "cert trusted in System keychain" \
    || security add-trusted-cert -d -r trustRoot -k ~/Library/Keychains/login.keychain-db "$CERT_PEM" \
       && echo "cert trusted in login keychain"
else
  echo "WARN: could not fetch cert; falling back to ignore-cert flag"
fi

echo "=== 3. write LaunchAgent ==="
cat > ~/Library/LaunchAgents/${PLIST_LABEL}.plist <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${PLIST_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${CHROME}</string>
    <string>--user-data-dir=${KA_DIR}</string>
    <string>--kiosk</string>
    <string>--app=https://${STRIX_HOST}:8443/index.html?power=full</string>
    <string>--autoplay-policy=no-user-gesture-required</string>
    <string>--disable-features=TranslateUI</string>
    <string>--force-device-scale-factor=1.0</string>
    <string>--noerrdialogs</string>
    <string>--disable-session-crashed-bubble</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>15</integer>
  <key>StandardOutPath</key><string>/tmp/ga-kiosk.log</string>
  <key>StandardErrorPath</key><string>/tmp/ga-kiosk.log</string>
</dict>
</plist>
PLIST

echo "=== 4. prevent display sleep while on AC (kiosk must stay up) ==="
sudo pmset -a sleep 0 displaysleep 0 disksleep 10 2>/dev/null \
  || echo "WARN: sudo failed — set Energy settings manually: never sleep on AC"

echo "=== 5. load it ==="
launchctl unload ~/Library/LaunchAgents/${PLIST_LABEL}.plist 2>/dev/null
launchctl load ~/Library/LaunchAgents/${PLIST_LABEL}.plist
sleep 4

if pgrep -f "kiosk.*8443" >/dev/null; then
  echo "kiosk chrome RUNNING"
else
  echo "WARN: kiosk not detected; check /tmp/ga-kiosk.log"
fi

echo "=== done. Verify from Strix: ss -tn | grep 8443 should show this iMac ==="