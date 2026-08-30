#!/usr/bin/env bash
# gtv-audio-watchdog.sh — self-heals the Jeeves audio routing on Strix.
#
# Failure mode (seen 3x as of 2026-08-30):
#   The Radeon HDMI card drops to the "off" profile on its own -> the HDMI
#   sink vanishes -> echo-cancel-playback falls back to the default sink
#   (HRTF virtual surround -> USB DAC) -> Jeeves' voice plays on headphones
#   -> mic hears it -> feedback loop.
#
# This watchdog detects BOTH signals and repairs:
#   1. HDMI sink missing from PipeWire -> re-set card profile (index 1).
#   2. echo-cancel-playback linked to anything other than the HDMI sink
#      -> disconnect from HRTF, relink to HDMI.
#
# Designed to run every minute from a systemd user timer. Output: single
# "OK" line when healthy, repair lines when it acts (cron-monitor friendly).

export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"

HDMI_SINK_NAME="alsa_output.pci-0000_c5_00.1.hdmi-stereo"
HRTF_INPUT="effect_input.virtual-surround-7.1-hrtf"
EC_PLAYBACK="echo-cancel-playback"
LOG="/tmp/gtv-audio-watchdog.log"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }

# --- 1. Is the HDMI sink present? -----------------------------------------
if ! wpctl status 2>/dev/null | grep -q "$HDMI_SINK_NAME\|Radeon.*HDMI"; then
    CARD=$(wpctl status 2>/dev/null | grep -iE "Radeon High Definition Audio Controller \[" | grep -oE "[0-9]+\." | tr -d ".")
    if [ -n "$CARD" ]; then
        log "REPAIR: HDMI sink missing; setting profile index 1 on card $CARD"
        wpctl set-profile "$CARD" 1 >/dev/null 2>&1
        sleep 3
    else
        log "ERROR: HDMI card itself missing from wpctl (no card id found)"
        exit 1
    fi
fi

# Re-check: did the sink come back?
if ! wpctl status 2>/dev/null | grep -qiE "Radeon.*HDMI"; then
    log "ERROR: profile reset did not restore the HDMI sink"
    exit 1
fi

# --- 2. Is echo-cancel-playback linked to HDMI? ----------------------------
CURRENT=$(pw-link -l 2>/dev/null | grep -A2 "^${EC_PLAYBACK}:output_FL" | grep -oE "\-> [^ ]+" | head -1)
if [ "$CURRENT" = "-> ${HDMI_SINK_NAME}:playback_FL" ]; then
    echo "OK"
    exit 0
fi

log "REPAIR: echo-cancel-playback linked to '$CURRENT' (expected $HDMI_SINK_NAME); relinking"

# Disconnect from whatever it grabbed (HRTF, default, etc.)
for ch in FL FR FC LFE RL RR SL SR; do
    pw-link -d "${EC_PLAYBACK}:output_$ch" "${HRTF_INPUT}:playback_$ch" >/dev/null 2>&1
done
# belt: also disconnect from any other sink it may have latched onto
for ch in FL FR; do
    pw-link -d "${EC_PLAYBACK}:output_$ch" "$(pactl get-default-sink 2>/dev/null):playback_$ch" >/dev/null 2>&1
done

sleep 1
pw-link "${EC_PLAYBACK}:output_FL" "${HDMI_SINK_NAME}:playback_FL" >/dev/null 2>&1
pw-link "${EC_PLAYBACK}:output_FR" "${HDMI_SINK_NAME}:playback_FR" >/dev/null 2>&1
sleep 1

FINAL=$(pw-link -l 2>/dev/null | grep -A2 "^${EC_PLAYBACK}:output_FL" | grep -oE "\-> [^ ]+" | head -1)
if [ "$FINAL" = "-> ${HDMI_SINK_NAME}:playback_FL" ]; then
    log "REPAIR OK: echo-cancel-playback relinked to HDMI"
    exit 0
fi
log "ERROR: relink failed; still '$FINAL'"
exit 1