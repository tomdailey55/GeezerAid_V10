#!/bin/bash
# install_ostt_andrea.sh — OSTT-style dictation on Andrea's iMac (`ga` user).
# Alt+Space → hold to talk → local whisper (Metal) → text into clipboard +
# active app. Privacy: everything local, no API keys.
#
# Design choice: use the proven open-source "superwhisper"-class flow via
# `whisper-cpp` + a tiny hotkey app, OR the actual OSTT project if present.
# This script installs whisper.cpp + a lightweight push-to-dictate binary.

set -u
echo "=== 1. whisper.cpp via brew (Metal accelerated on M4) ==="
brew install whisper-cpp 2>/dev/null && echo "whisper-cli installed"

echo "=== 2. download a small English model (fast on M4) ==="
MODELS_DIR="$HOME/.ga/models"
mkdir -p "$MODELS_DIR"
MODEL="$MODELS_DIR/ggml-base.en.bin"
[ -f "$MODEL" ] || curl -L -o "$MODEL" \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin
ls -la "$MODEL"

echo "=== 3. PTT dictation helper (hold V, or Alt+Space via Karabiner later) ==="
cat > "$HOME/.ga/dictate.sh" <<'EOF'
#!/bin/bash
# Hold-to-dictate: records until Enter pressed, transcripts to clipboard.
MODEL="$HOME/.ga/models/ggml-base.en.bin"
WAV="/tmp/ga-dictate.wav"
echo "🎙  recording... press Enter to stop"
rec -q "$MODEL.wav" silence 1 0.1 3% 1 2.0 3% 2>/dev/null || true
sox "$MODEL.wav" -r 16000 -c 1 -b 16 "$wav" 2>/dev/null || cp "$MODEL.wav" "$wav"
whisper-cli -m "$HOME/.ga/models/ggml-base.en.bin" -f "$wav" -otxt -of /tmp/ga-dictate
# copy text to clipboard
cat /tmp/ga-dictate.txt | pbcopy
echo "copied: $(cat /tmp/ga-dictate.txt)"
EOF
chmod +x "$HOME/.ga/dictate.sh"

echo "=== 3b. bind to Alt+Space (requires Hammerspoon or skhd; skhd is lighter) ==="
mkdir -p ~/.config/skhd
echo 'alt - space : ~/.ga/dictate.sh > /tmp/dictate.log 2>&1' > ~/.config/skhd/skhdrc 2>/dev/null || {
  mkdir -p ~/.config/skhd; echo 'alt - space : ~/.ga/dictate.sh > /tmp/dictate.log' > ~/.config/skhd/skhdrc; }
brew install skhd 2>/dev/null && skhd --start-service 2>/dev/null || echo "skhd: install manually if missing"

echo "=== done. Test: Alt+Space, speak, Enter → text in clipboard ==="