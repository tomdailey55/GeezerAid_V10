#!/usr/bin/env bash
# gtv-dialogue.sh — dialogue clarity for the Genius TV.
#
# "I can't hear the words" is the most common complaint about modern TV, and no
# TV solves it well. Three independent controls:
#
#   gtv-dialogue.sh boost on|off|status   # speech-band EQ in front of HDMI out
#   gtv-dialogue.sh louder [step]         # raise TV volume
#   gtv-dialogue.sh quieter [step]
#   gtv-dialogue.sh slower|faster|normal  # playback rate in the browser player
#
# WHY AN EQ AND NOT JUST VOLUME: turning everything up raises the explosions
# with the whispers. Dialogue lives roughly 1–4 kHz; lifting that band and
# gently cutting the low rumble makes speech intelligible WITHOUT making the
# room louder — which is the whole point for an elder-focused product.
#
# ROUTING NOTE (important): TV audio goes out the HDMI sink. The echo-cancel
# sink is a SEPARATE path used for Jeeves' voice/AEC. This filter is inserted
# in front of HDMI ONLY, so it can never colour the microphone path or the
# spoken replies.
set -uo pipefail

export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"

HDMI_SINK="${GTV_HDMI_SINK:-alsa_output.pci-0000_c5_00.1.hdmi-stereo}"
CONF_DIR="$HOME/.config/pipewire/pipewire.conf.d"
CONF="$CONF_DIR/gtv-dialogue.conf"
FILTER_NAME="gtv_dialogue"
DASH_URL="${GTV_DASH_URL:-http://127.0.0.1:8770}"

write_conf() {
  mkdir -p "$CONF_DIR"
  cat > "$CONF" <<EOF
# GTV dialogue-clarity filter — speech-band lift in front of HDMI output.
# Managed by gtv-dialogue.sh; safe to delete when 'boost off'.
context.modules = [
  { name = libpipewire-module-filter-chain
    args = {
      node.description = "Dialogue Clarity (Genius TV)"
      media.name       = "Dialogue Clarity"
      filter.graph = {
        nodes = [
          # Tame low-frequency rumble that masks consonants.
          { type = builtin  name = hp   label = bq_highpass
            control = { "Freq" = 90   "Q" = 0.7 } }
          # Main intelligibility lift: presence band.
          { type = builtin  name = pres label = bq_peaking
            control = { "Freq" = 2200 "Q" = 0.9  "Gain" = 5.5 } }
          # Consonant clarity (s, t, k) without harshness.
          { type = builtin  name = art  label = bq_peaking
            control = { "Freq" = 4000 "Q" = 1.1  "Gain" = 3.0 } }
          # Pull down the boom that competes with speech.
          { type = builtin  name = boom label = bq_peaking
            control = { "Freq" = 250  "Q" = 0.8  "Gain" = -3.0 } }
        ]
        links = [
          { output = "hp:Out"   input = "pres:In" }
          { output = "pres:Out" input = "art:In"  }
          { output = "art:Out"  input = "boom:In" }
        ]
        inputs  = [ "hp:In"   ]
        outputs = [ "boom:Out" ]
      }
      audio.channels  = 2
      audio.position  = [ FL FR ]
      capture.props = {
        node.name    = "$FILTER_NAME"
        media.class  = Audio/Sink
        node.description = "Dialogue Clarity (Genius TV)"
      }
      playback.props = {
        node.name    = "${FILTER_NAME}.out"
        node.passive = true
        target.object = "$HDMI_SINK"
      }
    }
  }
]
EOF
}

filter_id() {
  # Read the node id from pw-dump by node.name — wpctl's tree output is not a
  # reliable place to grep (indentation and markers vary between versions).
  pw-dump 2>/dev/null | python3 -c "
import sys, json
try:
    for n in json.load(sys.stdin):
        p = (n.get('info') or {}).get('props') or {}
        if p.get('node.name') == '$FILTER_NAME':
            print(n['id']); break
except Exception:
    pass
" 2>/dev/null
}

hdmi_id() {
  pw-dump 2>/dev/null | python3 -c "
import sys, json
try:
    for n in json.load(sys.stdin):
        p = (n.get('info') or {}).get('props') or {}
        if p.get('node.name') == '$HDMI_SINK':
            print(n['id']); break
except Exception:
    pass
" 2>/dev/null
}

case "${1:-status}" in
  boost)
    case "${2:-on}" in
      on)
        write_conf
        systemctl --user restart pipewire pipewire-pulse 2>/dev/null || true
        sleep 3
        id=$(filter_id)
        if [ -n "$id" ]; then
          wpctl set-default "$id" 2>/dev/null || true
          echo "dialogue boost ON (filter node $id, feeding $HDMI_SINK)"
        else
          echo "filter did not appear — check: journalctl --user -u pipewire -n 30"
          exit 1
        fi
        ;;
      off)
        rm -f "$CONF"
        systemctl --user restart pipewire pipewire-pulse 2>/dev/null || true
        sleep 3
        # Hand playback back to the TV's own output.
        hid=$(hdmi_id)
        [ -n "$hid" ] && wpctl set-default "$hid" 2>/dev/null || true
        echo "dialogue boost OFF (default sink restored)"
        ;;
      status|*)
        if [ -f "$CONF" ]; then echo "config: present"; else echo "config: absent"; fi
        id=$(filter_id); [ -n "$id" ] && echo "filter: loaded (node $id)" || echo "filter: not loaded"
        ;;
    esac
    ;;

  louder)   wpctl set-volume @DEFAULT_AUDIO_SINK@ "${2:-8}%+" && wpctl get-volume @DEFAULT_AUDIO_SINK@ ;;
  quieter)  wpctl set-volume @DEFAULT_AUDIO_SINK@ "${2:-8}%-" && wpctl get-volume @DEFAULT_AUDIO_SINK@ ;;
  volume)   wpctl get-volume @DEFAULT_AUDIO_SINK@ ;;

  slower|faster|normal)
    # Playback rate is a property of the HTML5 player, so it is set in the
    # browser rather than in the audio graph.
    rate=1.0
    [ "$1" = "slower" ] && rate="${2:-0.85}"
    [ "$1" = "faster" ] && rate="${2:-1.25}"
    curl -sf -m 8 -X POST "$DASH_URL/api/command" \
      -H 'Content-Type: application/json' \
      -d "{\"type\":\"rate\",\"rate\":$rate}" >/dev/null \
      && echo "playback rate -> $rate" \
      || echo "dashboard not reachable (rate applies to dashboard video)"
    ;;

  status)
    echo -n "default sink volume: "; wpctl get-volume @DEFAULT_AUDIO_SINK@ 2>/dev/null
    [ -f "$CONF" ] && echo "dialogue boost: config present" || echo "dialogue boost: off"
    id=$(filter_id); [ -n "$id" ] && echo "filter node: $id"
    ;;

  *)
    echo "usage: gtv-dialogue.sh {boost on|off|status|louder|quieter|volume|slower|faster|normal|status}"
    exit 1
    ;;
esac
