#!/bin/bash
# Deploy GeezerAid V10 server: stop v9, start v10, verify.
# Run from a normal terminal (NOT from inside the Hermes gateway).
set -u
UID_NUM=$(id -u)

echo "=== stopping server-v9 ==="
launchctl bootout gui/$UID_NUM/com.geezeraid.server-v9 2>&1
sleep 2

echo "=== loading server-v10 ==="
launchctl bootstrap gui/$UID_NUM "$HOME/Library/LaunchAgents/com.geezeraid.server-v10.plist" 2>&1
sleep 6

echo "=== port 8766 owner ==="
lsof -iTCP:8766 -sTCP:LISTEN 2>/dev/null | head -2

echo "=== launchctl state ==="
launchctl list 2>/dev/null | grep -iE "server-v9|server-v10"

echo "=== health check ==="
curl -s -m3 http://127.0.0.1:8766/health 2>&1 | head -c 200
echo
echo "=== v10 server log tail ==="
tail -5 "$HOME/Library/Logs/GeezerAid/v10-server.log" 2>/dev/null
