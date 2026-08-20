#!/usr/bin/env python3
"""
GeezerAid V9 — "Jeeves" always-on smart-speaker front-end (Linux prototype)

A cheap plugged-in laptop becomes a voice assistant / smart-speaker:
  - Always listening for the wake phrase "Hey Jeeves" (offline, VAD-gated).
  - On wake: records a query, transcribes locally (whisper), sends to the
    GeezerAid V9 server (Mac) and speaks the reply.
  - understands "play <song> on youtube" -> streams via yt-dlp + ffplay.
  - Fullscreen ambient GUI shows idle / listening / thinking / playing state,
    with a LIVE VU / spectrum meter driven by the real mic input level.

Wake-word is local + keyless: we use Voice Activity Detection to skip silence,
then a short whisper pass (model 'base' by default — 'tiny' garbles the
wake word) and a fuzzy/phonetic match for "jeeves". No cloud, no API key.

A single continuous mic monitor (arecord) owns the microphone. It powers both
the live meter and the wake/query capture (audio is buffered in a rolling
ring), so there is never a double-open on the mic.

Run:
  ./jeeves_speaker.py --gui                 # fullscreen ambient + VU meter
  ./jeeves_speaker.py --gui --with-video    # also show YouTube video
  ./jeeves_speaker.py --no-gui              # headless always-on daemon

Design notes:
  - Reuses linux_client.chat() / play_audio() so the server contract stays frozen.
  - This box (Strix) is DEV-ONLY; the server it calls is the Mac (Tailscale IP).
"""
import argparse
import collections
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
try:
    import tkinter as tk
except ImportError:
    tk = None  # tkinter not available (e.g. Python 3.14 venv) — ambient GUI isn't required
import queue
import wave
import audioop
import numpy as np
from datetime import datetime, timedelta

import linux_client as lc

# ═══════════════════════════════════════════════════════════════════
# Config
# ═══════════════════════════════════════════════════════════════════
WAKE_PHRASES = ("hey jeeves", "hi jeeves", "ok jeeves", "jeeves")
# 'default' is the JLAB USB mic on this box (PipeWire routes default ->
# JLAB TALK MICROPHONE). Raw hw:2,0 is dead here; use 'default'.
# Only ONE instance may own the mic at a time — enforced by a lockfile below.
MIC_DEVICE = os.getenv("GA_MIC_DEVICE", "default")
MIC_FALLBACK = "default"
REC_SECS = float(os.getenv("GA_REC_SECS", "5"))
WHISPER_MODEL = os.getenv("GA_WHISPER_MODEL", "base")
# whisper.cpp (Vulkan/GPU) fast path — use it when present for much faster
# and more accurate transcription on Strix's Radeon 8060S. Falls back to the
# pip openai-whisper CPU model if the CLI/model are missing.
WHISPER_CLI = os.getenv("GA_WHISPER_CLI", os.path.expanduser("~/whisper.cpp/build/bin/whisper-cli"))
WHISPER_GGUF = os.getenv("GA_WHISPER_GGUF", os.path.expanduser("~/whisper.cpp/models/ggml-large-v3.bin"))
RATE = 16000
METER_BARS = 16
VAD_THRESHOLD = float(os.getenv("GA_VAD_THRESHOLD", "0.12"))   # normalized RMS above this = speech present
# Two-state sensitivity: WAKE mode (hunting "Hey Jeeves", user raises voice)
# uses a HIGHER threshold above the noise floor; CONVERSATION mode (follow-ups,
# normal voice) uses a LOWER threshold. Both track the live noise floor so they
# adapt to a varying room. Base offsets above the running noise floor:
VAD_WAKE_ABOVE = float(os.getenv("GA_VAD_WAKE_ABOVE", "0.10"))    # wake threshold = noise_floor + this
VAD_TALK_ABOVE = float(os.getenv("GA_VAD_TALK_ABOVE", "0.04"))    # conversation threshold = noise_floor + this
NOISE_SMOOTH = 0.02        # how fast the noise floor adapts (slow = stable)
LEVEL_SCALE = 6000.0       # RMS value mapped to "full" on the meter
BUF_SECS = 12              # rolling audio buffer depth (seconds)
HERE = os.path.dirname(os.path.abspath(__file__))
WAKE_LOG = os.path.join(HERE, "jeeves_wake_log.jsonl")  # intention-processor tuning data
MIC_LOCK = os.path.join(HERE, ".jeeves_mic.lock")        # single-instance mic guard


def acquire_mic_lock():
    """Ensure only one Jeeves instance owns the mic. Returns True if we hold
    it; prints a clear instruction and returns False if another instance has
    it (two arecord -D default readers collide -> silent second instance).

    A crash or hard restart leaves the lock file behind naming a PID that no
    longer exists, which blocked every subsequent start until the file was
    removed by hand. So a lock is only honoured when its PID is actually alive
    AND is really a Jeeves process — otherwise it is stale and gets reclaimed.
    """
    import errno

    def _pid_alive(pid: int) -> bool:
        """True if pid exists and looks like our own program (not a recycled id)."""
        try:
            os.kill(pid, 0)          # signal 0 = existence check only
        except ProcessLookupError:
            return False
        except PermissionError:
            return True              # exists but owned by someone else
        except Exception:
            return False
        # PIDs get reused; confirm it really is a jeeves_speaker process before
        # trusting the lock, or an unrelated program inheriting the number
        # would keep the mic locked forever.
        #
        # /proc only exists on Linux. Where it is absent (macOS) the process is
        # alive and we must NOT treat it as stale — doing so would defeat the
        # single-instance guard, which is the whole point of the lock.
        cmdline = f"/proc/{pid}/cmdline"
        if not os.path.exists("/proc"):
            return True              # non-Linux: alive is good enough
        try:
            with open(cmdline, "rb") as f:
                return b"jeeves_speaker" in f.read()
        except FileNotFoundError:
            return False             # Linux and the proc entry vanished: dead
        except Exception:
            return True              # unreadable: assume genuine, stay safe

    for attempt in (1, 2):
        try:
            fd = os.open(MIC_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise
            try:
                with open(MIC_LOCK) as f:
                    raw = f.read().strip()
                pid = int(raw)
            except Exception:
                pid, raw = -1, "?"

            # Stale lock (dead PID, or a PID that isn't Jeeves): reclaim it.
            if pid <= 0 or not _pid_alive(pid):
                if attempt == 1:
                    print(f"[mic] clearing stale lock from pid {raw} "
                          f"(no longer running)", file=sys.stderr)
                    try:
                        os.unlink(MIC_LOCK)
                    except FileNotFoundError:
                        pass
                    continue         # retry the create
                return False         # lost a race with another starter

            print(f"[mic] another Jeeves instance (pid {raw}) already owns the "
                  f"microphone. Stop it first:\n"
                  f"      systemctl --user stop geezeraid-jeeves.service\n"
                  f"  or: kill {raw}", file=sys.stderr)
            return False
    return False

# Palette (warm, ambient, low-glare for a bedside/kitchen device)
C_BG = "#0e1116"
C_IDLE = "#1b2735"
C_LISTEN = "#1f6feb"
C_THINK = "#b98a00"
C_PLAY = "#1a7f4b"
C_TEXT = "#e6edf3"
C_SUB = "#8b949e"


# ═══════════════════════════════════════════════════════════════════
# Audio cues (generated, no asset files needed)
# ═══════════════════════════════════════════════════════════════════
def _beep(freq=660, dur=0.12, vol=0.3):
    """Tiny sine blip through the default player for state feedback."""
    try:
        import math
        import struct
        path = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        n = int(44100 * dur)
        with wave.open(path, "w") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(44100)
            for i in range(n):
                v = int(32767 * vol * math.sin(2 * math.pi * freq * i / 44100))
                w.writeframes(struct.pack("<h", v))
        name, pargs = lc._detect_player()
        subprocess.run(pargs + [path], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
        os.unlink(path)
    except Exception:
        pass


def chime_wake():
    """Soft two-note rise = 'I heard you'."""
    _audio_guard()
    _beep(523, 0.10, 0.25)
    time.sleep(0.08)
    _beep(784, 0.12, 0.25)


def chime_think():
    _audio_guard()
    _beep(440, 0.08, 0.2)


def chime_play():
    _audio_guard()
    _beep(392, 0.10, 0.22)
    time.sleep(0.07)
    _beep(587, 0.12, 0.22)


# ═══════════════════════════════════════════════════════════════════
# Mic ducking: while Jeeves is producing audio (chimes + TTS replies),
# the mic must be IGNORED, otherwise it hears its own voice and
# re-wakes itself (feedback loop -> "continuation fails").
_audio_until = 0.0          # monotonic time until which the mic is ducked
_AUDIO_COOLDOWN = 1.2       # seconds of silence after audio before re-listening


def _speaking_until():
    return time.monotonic() + _AUDIO_COOLDOWN


def speaking():
    """True while Jeeves is (or just finished) playing audio -> duck the mic.
    Checks BOTH the local cooldown AND linux_client's playback flag (set for
    the full TTS duration) so we don't hear our own reply and re-respond."""
    if time.monotonic() < _audio_until:
        return True
    if getattr(lc, "_speaking_until", 0.0) > time.monotonic():
        return True
    return False


def _audio_guard():
    """Call before/while producing audio so the wake loop ignores our own voice."""
    global _audio_until
    _audio_until = _speaking_until()
# Every audio event (VAD speech, wake hit/miss, query, empty, response,
# youtube) is appended as one JSON line with the raw whisper transcript so we
# can measure false-wake rate, missed wakes, and transcript quality.
# ═══════════════════════════════════════════════════════════════════
def log_wake(event, **fields):
    """Append one tuning event to jeeves_wake_log.jsonl."""
    entry = {
        "ts": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "unix": round(time.time(), 3),
        "event": event,
    }
    entry.update(fields)
    try:
        with open(WAKE_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[log error] {e}", file=sys.stderr)


# ═══════════════════════════════════════════════════════════════════
# Continuous mic monitor — single owner of the microphone.
# Powers BOTH the live VU meter and the wake/query audio capture.
# ═══════════════════════════════════════════════════════════════════
class MicMonitor(threading.Thread):
    def __init__(self, device=MIC_DEVICE, rate=RATE, bars=METER_BARS):
        super().__init__(daemon=True)
        self.device = device
        self.rate = rate
        self.bars = bars
        self.level = 0.0                 # smoothed normalized RMS (0..1)
        self.bar_levels = [0.0] * bars   # per-bar smoothed magnitude (0..1)
        self.vad = False                 # speech present?
        self.buf = collections.deque(maxlen=int(rate * 2 * BUF_SECS))
        self._stop = False
        self.available = False           # mic opened successfully?
        self.device_used = None          # which -D actually opened
        self.signal = False              # is real audio arriving (not silence)?
        # Adaptive noise-floor + two-state sensitivity
        self.noise_floor = 0.05          # running estimate of room ambient (0..1)
        self.sensitivity = "wake"        # "wake" (higher thresh) | "talk" (lower thresh)

    def _current_vad_threshold(self):
        """Threshold = noise floor + mode offset. WAKE mode is higher (user
        raises voice for 'Hey Jeeves'); TALK mode is lower (normal voice)."""
        if self.sensitivity == "talk":
            return max(0.02, self.noise_floor + VAD_TALK_ABOVE)
        return max(0.03, self.noise_floor + VAD_WAKE_ABOVE)

    def set_sensitivity(self, mode):
        """Switch sensitivity: 'wake' (higher) before/while hunting the wake
        word; 'talk' (lower) once in conversation."""
        if mode in ("wake", "talk"):
            self.sensitivity = mode

    def run(self):
        devices = [self.device, MIC_FALLBACK]
        while not self._stop:
            opened = None
            for dev in devices:
                try:
                    proc = subprocess.Popen(
                        ["arecord", "-D", dev, "-f", "S16_LE",
                         "-r", str(self.rate), "-c", "1", "-t", "raw"],
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    )
                    opened = (proc, dev)
                    break
                except Exception as e:
                    print(f"[mic] {dev} unavailable: {e}", file=sys.stderr)
            if opened is None:
                self.available = False
                time.sleep(3)
                continue
            proc, dev = opened
            self.device_used = dev
            self.available = True
            chunk = self.rate // 8        # 125 ms of frames
            bytes_per = chunk * 2
            silent_for = 0.0
            while not self._stop:
                raw = proc.stdout.read(bytes_per)
                if not raw:
                    break
                self.buf.extend(raw)
                rms = audioop.rms(raw, 2)
                norm = min(1.0, rms / LEVEL_SCALE)
                self.level = self.level * 0.6 + norm * 0.4
                # Adaptive noise-floor: slowly track ambient when not speaking.
                # Only feed quiet samples (below current threshold) so loud
                # speech doesn't push the floor up. Low-pass adapts to a room.
                thresh = self._current_vad_threshold()
                if not self.vad and self.level < thresh:
                    self.noise_floor = self.noise_floor * (1 - NOISE_SMOOTH) + self.level * NOISE_SMOOTH
                # Current threshold depends on mode: higher while hunting the
                # wake word (user raises voice), lower once in conversation.
                self.vad = self.level > thresh
                self.signal = self.level > 0.01   # any real audio at all
                # log-spaced spectrum for a voice-like meter: map the chunk's
                # FFT onto a few octaves so bars correspond to pitch bands,
                # then SCALE by loudness so the meter tracks volume.
                arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
                spec = np.abs(np.fft.rfft(arr))
                # log-spaced band energies (skip DC, cover ~80Hz..8kHz)
                nb = self.bars
                lo, hi = 1, len(spec) - 1
                edges = np.logspace(np.log10(lo), np.log10(hi), nb + 1).astype(int)
                bands = np.array([
                    spec[edges[i]:edges[i + 1]].mean()
                    if edges[i + 1] > edges[i] else 0.0
                    for i in range(nb)
                ])
                bmax = bands.max()
                if bmax > 0:
                    bands = bands / bmax          # shape (0..1)
                loud = min(1.0, self.level * 3.0)  # whisper->shout range
                for i in range(nb):
                    target = bands[i] * loud
                    self.bar_levels[i] = self.bar_levels[i] * 0.5 + target * 0.5
            try:
                proc.terminate()
                proc.stdout.close()
            except Exception:
                pass
            if self._stop:
                break
            time.sleep(1)   # arecord died unexpectedly; retry

    def snapshot(self, secs):
        """Return a path to a WAV holding the last `secs` of buffered audio."""
        nbytes = int(self.rate * 2 * secs)
        data = bytes(self.buf)[-nbytes:]
        if len(data) < self.rate:        # too little audio; pad with silence
            data = data + b"\x00" * (self.rate - len(data))
        path = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        with wave.open(path, "w") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.rate)
            w.writeframes(data)
        return path

    def stop(self):
        self._stop = True


# ═══════════════════════════════════════════════════════════════════
# GUI (ambient fullscreen + live VU meter)
# ═══════════════════════════════════════════════════════════════════
class AmbientGUI:
    def __init__(self, root):
        self.root = root
        self.root.configure(bg=C_BG)
        self.root.attributes("-fullscreen", True)
        self.root.bind("<Escape>", lambda e: self.root.destroy())
        self.root.bind("<q>", lambda e: self.root.destroy())
        self.monitor = None
        self.state_color = C_IDLE
        # Thread-safe dispatch queue: background threads (wake/respond loop,
        # timer threads) push callbacks here; a main-thread poller drains them.
        # Using root.after(0, ...) directly from a bg thread is UNRELIABLE in
        # this Tk build — callbacks silently never run, so captions/orb updates
        # from the voice loop were being dropped. The queue fixes that.
        self._q = queue.Queue()
        self.root.after(40, self._drain)

        # clock (top)
        self.clock = tk.Label(root, text="", font=("DejaVu Sans", 22),
                              fg=C_SUB, bg=C_BG)
        self.clock.place(relx=0.5, rely=0.08, anchor="n")

        # central "orb" — a bordered frame whose bg color = state.
        # (No canvas: canvas GC churn SEGVs on some display backends.)
        self.orb = tk.Frame(root, width=220, height=220, bg=C_IDLE,
                            relief="ridge", borderwidth=10)
        self.orb.place(relx=0.5, rely=0.40, anchor="center")

        # LIVE VU / spectrum meter — vertical bars, grows upward with mic level
        self.meter = tk.Frame(root, bg=C_BG, width=600, height=96)
        self.meter.place(relx=0.5, rely=0.62, anchor="center")
        self.bar_frames = []
        bw = 600 // METER_BARS
        for i in range(METER_BARS):
            b = tk.Frame(self.meter, bg=C_IDLE, width=bw - 4, height=4)
            b.place(x=i * bw, y=92, anchor="sw")   # anchor sw -> grows upward
            self.bar_frames.append(b)

        # caption (what Jeeves is doing / heard text)
        self.caption = tk.Label(root, text="Say “Hey Jeeves”",
                                font=("DejaVu Sans", 26, "bold"),
                                fg=C_TEXT, bg=C_BG, wraplength=900,
                                justify="center")
        self.caption.place(relx=0.5, rely=0.76, anchor="center")

        # sub-line (now playing / latency / mic status)
        self.sub = tk.Label(root, text="", font=("DejaVu Sans", 16),
                            fg=C_SUB, bg=C_BG, wraplength=900, justify="center")
        self.sub.place(relx=0.5, rely=0.86, anchor="center")

        self._pulse = 0
        self._tick_clock()
        self._breathe()

    def attach(self, monitor):
        """Wire the live mic monitor to the meter and start drawing."""
        self.monitor = monitor
        self._draw_meter()

    # ── thread-safe dispatch ──
    # Tkinter is NOT thread-safe: the wake/respond loop runs in a background
    # thread, so all widget updates must be marshalled to the main thread.
    def call(self, fn, *a):
        # Thread-safe: push to the queue; the main-thread _drain runs it.
        self._q.put((fn, a))

    def _drain(self):
        # Main-thread poller: run any pending callbacks from bg threads.
        try:
            while True:
                fn, a = self._q.get_nowait()
                try:
                    fn(*a)
                except Exception:
                    import traceback
                    traceback.print_exc()
        except queue.Empty:
            pass
        self.root.after(40, self._drain)

    # ── state setters ──
    def _set_color(self, color):
        self.state_color = color
        self.orb.configure(bg=color)

    def set_idle(self):
        self._set_color(C_IDLE)
        self.caption.config(text="Say “Hey Jeeves”", fg=C_TEXT)
        self.sub.config(text="")

    def set_listening(self):
        self._set_color(C_LISTEN)
        self.caption.config(text="Listening…", fg=C_TEXT)
        self.sub.config(text="")

    def set_thinking(self):
        self._set_color(C_THINK)
        self.caption.config(text="Thinking…", fg=C_TEXT)
        self.sub.config(text="")

    def set_reply(self, text):
        self._set_color(C_PLAY)
        self.caption.config(text=text, fg=C_TEXT)

    def set_playing(self, title):
        self._set_color(C_PLAY)
        self.caption.config(text="▶  Now Playing", fg=C_TEXT)
        self.sub.config(text=title)

    def set_transcript(self, text):
        self.sub.config(text=text[:90])

    # ── animations ──
    def _breathe(self):
        # gentle border pulse — safe Tk op (no canvas GC churn).
        # Blend the slow breathe with the live mic level so the orb visibly
        # "reacts" to your voice (brighter/bigger when you speak).
        self._pulse = (self._pulse + 1) % 360
        import math
        breathe = 0.5 + 0.5 * math.sin(math.radians(self._pulse))
        lvl = 0.0
        if self.monitor is not None:
            lvl = min(1.0, self.monitor.level * 3.0)
        w = 8 + int(6 * breathe) + int(8 * lvl)
        # border grows with the breathe AND with live mic level, so the orb
        # visibly "reacts" when you speak (bigger ring while talking).
        self.orb.configure(borderwidth=w)
        self.root.after(50, self._breathe)

    def _draw_meter(self):
        if self.monitor is not None:
            m = self.monitor
            if not m.available:
                # mic dead / unplugged -> flat dead bars + warning
                for b in self.bar_frames:
                    b.configure(height=3, bg="#5a1a16")
                self.sub.config(text="⚠ mic unavailable")
            elif not m.signal:
                # open but silent -> flat red bars (dead look), NOT jittering
                for b in self.bar_frames:
                    b.configure(height=3, bg="#b3261e")
                if not getattr(self, "_warned", False):
                    self.sub.config(text="⚠ mic: no signal — check input / say something")
                    self._warned = True
            else:
                # real signal -> live spectrum in the current state color
                col = self.state_color
                for i, b in enumerate(self.bar_frames):
                    lvl = m.bar_levels[i]
                    h = max(3, int(lvl * 88))
                    b.configure(height=h, bg=col)
                # we're hearing something now -> clear the no-signal warning
                self._warned = False
                if self.state_color == C_IDLE:
                    self.sub.config(text="")
        self.root.after(50, self._draw_meter)

    def _tick_clock(self):
        now = datetime.now().strftime("%I:%M %p")
        self.clock.config(text=now)
        self.root.after(1000, self._tick_clock)


# ═══════════════════════════════════════════════════════════════════
# Wake-word + capture (fed by the MicMonitor ring buffer)
# ═══════════════════════════════════════════════════════════════════
def _rms(wav_path):
    """Mean RMS of a 16-bit mono WAV (silence detector)."""
    import struct
    try:
        with open(wav_path, "rb") as f:
            f.read(44)  # skip header
            data = f.read()
        if not data:
            return 0.0
        n = len(data) // 2
        samples = struct.unpack("<%dh" % n, data[:n * 2])
        return (sum(s * s for s in samples) / max(n, 1)) ** 0.5
    except Exception:
        return 0.0


# Warm-loaded whisper model (loaded once, reused across transcriptions).
# The CLI subprocess cold-loads the model every call (~3-4s each); keeping it
# in memory makes follow-up transcriptions near-instant.
_WHISPER_MODEL = None
_WHISPER_LOCK = threading.Lock()


def _get_whisper(model=WHISPER_MODEL):
    global _WHISPER_MODEL
    if _WHISPER_MODEL is None:
        import whisper
        with _WHISPER_LOCK:
            if _WHISPER_MODEL is None:
                _WHISPER_MODEL = whisper.load_model(model, device="cpu")
    return _WHISPER_MODEL


def _transcribe(wav_path, model=WHISPER_MODEL):
    # Preferred: whisper.cpp on the GPU (Radeon 8060S, Vulkan) — far faster
    # and more accurate than the pip CPU model, especially for large-v3.
    if os.path.exists(WHISPER_CLI) and os.path.exists(WHISPER_GGUF):
        try:
            r = subprocess.run(
                [WHISPER_CLI, "-m", WHISPER_GGUF, "-f", wav_path,
                 "-t", "4", "-np", "--no-timestamps"],
                capture_output=True, text=True, timeout=30,
            )
            txt = (r.stdout or "").strip()
            lines = [ln for ln in txt.splitlines()
                     if not ln.startswith("ggml_") and not ln.startswith("system_info")
                     and ln.strip()]
            if lines:
                text = "\n".join(lines).strip()
                try:
                    os.unlink(wav_path)
                except OSError:
                    pass
                return text
            # no usable text — fall through to the pip CPU path
        except Exception:
            pass  # fall through
    try:
        import whisper
        m = _get_whisper(model)
        result = m.transcribe(wav_path, fp16=False)
        text = (result.get("text") or "").strip()
    except Exception:
        # fall back to the CLI if the in-process model fails
        txt_path = wav_path.rsplit(".", 1)[0] + ".txt"
        subprocess.run(
            ["whisper", wav_path, "--model", model, "--device", "cpu",
             "--output_format", "txt", "--output_dir", tempfile.gettempdir(),
             "--fp16", "False", "--verbose", "False"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        text = ""
        try:
            with open(txt_path) as f:
                text = f.read().strip()
        except FileNotFoundError:
            pass
        try:
            os.unlink(txt_path)
        except OSError:
            pass
    try:
        os.unlink(wav_path)
    except OSError:
        pass
    return text


def wake_detected(text):
    """Fuzzy + phonetic match for the wake phrase.

    'tiny' whisper habitually garbles 'jeeves' as 'jigs', 'judes', 'jeeps',
    'jages', 'hages', 'hate you's', 'judes', etc. We accept:
      - exact substring of any WAKE_PHRASES, OR
      - a token within fuzzy distance 0.6 of 'jeeves' (difflib), OR
      - a known phonetic variant.
    The preceding 'hey/hi/ok' is optional (so 'jeeves' alone also wakes)."""
    import re
    t = " " + text.lower().strip() + " "
    # 1) exact phrase substring
    if any(p in t for p in WAKE_PHRASES):
        return True
    # 2) phonetic variants — require an actual jeeves-like token. The wake
    #    word is 'jeeves'; 'hey/hi/ok' are optional prefixes and MUST NOT
    #    wake by themselves (that let 'hey jean'/'hey porthag'/TV noise
    #    trigger Jeeves). Only jeeves-variants count.
    jeeves_tokens = ("jeeves", "jigs", "jigs.", "jude", "judes", "jude's",
                     "jeeps", "jeeps.", "jeep's", "jages", "hages", "hage",
                     "jeeve", "jev", "javez", "javis", "jeevus", "jews")
    # multi-word phonetic variant: whisper hears "hey jeeves" as "hate you"
    if "hate you" in t or "hate yous" in t:
        return True
    toks = re.findall(r"[a-z']+", t)
    for tok in toks:
        if tok in jeeves_tokens:
            return True
        # fuzzy: any token close to 'jeeves' — but NOT 'hey'/'hay'/generic
        import difflib
        if tok not in ("hey", "hay", "hi", "ok", "hey there") and \
           difflib.SequenceMatcher(None, tok, "jeeves").ratio() >= 0.6:
            return True
    return False


def listen_for_wake(monitor, gui):
    """Loop on the live VAD flag; once speech is heard, snapshot + check
    for the wake phrase. Returns when 'hey jeeves' is detected."""
    # WAKE sensitivity: higher threshold — user raises voice for 'Hey Jeeves'.
    monitor.set_sensitivity("wake")
    while True:
        # duck the mic while we're producing audio (chimes / TTS) so we
        # don't re-wake on our own voice (feedback loop).
        if speaking():
            time.sleep(0.1)
            continue
        if monitor.vad:
            level = round(monitor.level, 3)
            time.sleep(1.2)                      # let the phrase finish
            wav = monitor.snapshot(2.6)
            rms = _rms(wav)
            if rms < 200:                        # still basically silent
                log_wake("speech_ignored", reason="silence_after_vad",
                         level=level, rms=round(rms, 1))
                os.unlink(wav)
                continue
            text = _transcribe(wav).lower()
            if wake_detected(text):
                log_wake("wake_hit", transcript=text, level=level,
                         rms=round(rms, 1))
                return True
            # not the wake word; keep listening (cheap, no server call)
            log_wake("wake_miss", transcript=text, level=level,
                     rms=round(rms, 1))
        else:
            time.sleep(0.08)


def capture_query(monitor, secs=REC_SECS):
    """After wake: capture the command. This user speaks the command in the
    SAME breath as the wake word ('hey jeeves what time is it'), so the
    command is in the PAST buffer, not after a pause. Snapshot the past
    (which contains the command) rather than recording forward."""
    # Snapshot the past ~4s — contains the command spoken right after wake
    wav = monitor.snapshot(secs)
    rms = _rms(wav)
    if rms < 150:
        log_wake("query_empty", reason="silent", rms=round(rms, 1))
        os.unlink(wav)
        return ""
    text = _transcribe(wav)
    # strip a leading wake phrase if whisper included it
    low = text.lower()
    for w in ("hey jeeves", "hey jeeves,", "hey jeeves.", "ok jeeves", "jeeves"):
        if low.startswith(w):
            text = text[len(w):].strip(" ,.")
            break
    log_wake("query", transcript=text, rms=round(rms, 1))
    return text


def wait_for_speech(monitor, timeout=20):
    """Wait up to `timeout` seconds for VAD to trigger. With AEC active the
    mic is cancelled against our own playback, so we can listen even while
    Jeeves speaks — this lets 'Mute, Jeeves' break in mid-sentence. Returns
    True if speech was heard, False on idle timeout."""
    start = time.time()
    while time.time() - start < timeout:
        if monitor.vad:
            return True
        time.sleep(0.08)
    return False


def is_exit_phrase(text):
    """Phrases that end the conversation and return to wake-word listening."""
    for p in ("goodbye", "good bye", "that's all", "that is all",
              "never mind", "exit", "bye", "see you"):
        if p in text:
            return True
    return False


def is_mute_phrase(text):
    """Restricted mute phrases — EXACTLY 'mute jeeves' and 'quiet jeeves'.
    Deliberately excludes bare 'mute'/'quiet'/'shut up'/'stop talking' so
    yelling at the dogs or other loud speech never mutes Jeeves accidentally."""
    t = text.replace(",", " ").replace("  ", " ").strip()
    return "mute jeeves" in t or "quiet jeeves" in t


def conversation_loop(monitor, gui, with_video, idle_timeout=20):
    """After wake, stay in a conversation: capture command -> respond ->
    capture next -> respond, until an exit phrase or idle timeout. No need to
    repeat 'hey jeeves' for follow-ups."""
    # TALK sensitivity: lower threshold — normal voice for follow-ups.
    monitor.set_sensitivity("talk")
    while True:
        if not wait_for_speech(monitor, idle_timeout):
            break  # idle timeout — back to wake-word listening
        if gui:
            gui.call(gui.set_listening)
        time.sleep(0.5)                      # let the phrase finish
        wav = monitor.snapshot(3.0)
        rms = _rms(wav)
        if rms < 150:
            os.unlink(wav)
            continue
        text = _transcribe(wav).lower()
        # MUTE: stop any in-flight TTS immediately, then keep listening.
        if is_mute_phrase(text):
            lc.stop_audio()
            log_wake("mute", transcript=text)
            if gui:
                gui.call(gui.set_transcript, "Muted.")
            continue
        if is_exit_phrase(text):
            if gui:
                gui.call(gui.set_reply, "Goodbye.")
                time.sleep(2)
            log_wake("conversation_end", reason="exit_phrase", transcript=text)
            break
        if not text:
            continue
        print(f"[heard] {text}")
        if gui:
            gui.call(gui.set_transcript, text)
        handle_query(text, gui, with_video)
    if gui:
        gui.call(gui.set_idle)


# ═══════════════════════════════════════════════════════════════════
# YouTube intent
# ═══════════════════════════════════════════════════════════════════
def play_youtube(query, with_video=False, gui=None):
    """Resolve a YouTube search and stream via yt-dlp + ffplay."""
    term = query.lower().replace("play", "", 1).replace("on youtube", "").strip()
    if not term:
        return False
    try:
        if gui:
            gui.call(gui.set_playing, f"searching: {term}")
        # resolve one result
        out = subprocess.run(
            ["yt-dlp", "--print", "%(title)s|%(webpage_url)s", "--no-warnings",
             f"ytsearch1:{term}"],
            capture_output=True, text=True, timeout=40,
        )
        line = (out.stdout or "").strip().splitlines()[0]
        if "|" not in line:
            return False
        title, url = line.split("|", 1)
        if gui:
            gui.call(gui.set_playing, title)
        chime_play()
        fmt = "best" if with_video else "bestaudio"
        player = ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]
        if with_video:
            player = ["ffplay", "-autoexit", "-loglevel", "quiet"]
        # stream pipe: yt-dlp stdout -> ffplay stdin
        ytdlp = subprocess.Popen(
            ["yt-dlp", "-f", fmt, "-o", "-", url],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        ff = subprocess.Popen(player, stdin=ytdlp.stdout,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ytdlp.stdout.close()
        ff.wait()
        ytdlp.wait()
        return True
    except Exception as e:
        print(f"[youtube] error: {e}", file=sys.stderr)
        return False


# ═══════════════════════════════════════════════════════════════════
# Local timers & reminders — fired on-device, NOT via the server.
# The server's canned "timer" response is a stub; real execution lives here
# so GA is a genuine smart speaker (the one thing the YouTube build showed off).
# Unified trigger grammar (mirror this on iOS):
#   "set a timer for 10 minutes" / "timer 5m"
#   "remind me to call tom at 3pm" / "remind me to take meds in 2 hours"
#   "wake me at 7am" / "alarm 6:30"
# ═══════════════════════════════════════════════════════════════════
import re

_timers = []          # list of active timer dicts (for status display)
_timers_lock = threading.Lock()


def _parse_duration(text):
    """'10 minutes' / '5m' / '2 hours' / '90s' -> seconds (float) or None."""
    m = re.search(r"(\d+)\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes|"
                  r"h|hr|hrs|hour|hours|d|day|days)\b", text)
    if not m:
        return None
    n = float(m.group(1))
    unit = m.group(2)[0]
    mult = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
    return n * mult


def _parse_clock(text):
    """'3pm' / '7:30 am' / '18:00' -> seconds until then (today/tomorrow) or None.

    Only matches EXPLICIT clock forms — an hour WITH EITHER a minutes part
    (':MM') OR an am/pm suffix. A bare number like '2' or '30' (which the
    duration parser owns) must NOT match, so reminders like "in 2 hours" or
    "in 30 minutes" are handled as durations, not clock times.
    """
    # alt 1: HH:MM with optional am/pm  (e.g. '7:30 am', '18:00')
    # alt 2: HH with mandatory am/pm    (e.g. '7am', '3pm')
    m1 = re.search(r"\b(\d{1,2}):(\d{2})(?:\s*(am|pm))?\b", text)
    if m1:
        h = int(m1.group(1))
        mi = int(m1.group(2))
        ap = m1.group(3)
    else:
        m2 = re.search(r"\b(\d{1,2})\s*(am|pm)\b", text)
        if not m2:
            return None
        h = int(m2.group(1))
        mi = 0
        ap = m2.group(2)
    if ap == "pm" and h < 12:
        h += 12
    elif ap == "am" and h == 12:
        h = 0
    now = datetime.now()
    try:
        then = now.replace(hour=h, minute=mi, second=0, microsecond=0)
    except ValueError:
        # out-of-range hour/minute (defensive — should not happen with the
        # digit regex, but guards against any future pathological input)
        return None
    if then <= now:
        then += timedelta(days=1)
    return (then - now).total_seconds()


def _timer_fire(entry, gui):
    try:
        with _timers_lock:
            if entry in _timers:
                _timers.remove(entry)
        label = entry["label"]
        # urgent triple-chime
        for _ in range(3):
            chime_play()
            time.sleep(0.18)
        msg = f"⏰ {label}"
        if gui:
            gui.call(gui.set_reply, msg)
            time.sleep(6)              # hold the alert on screen
            gui.call(gui.set_idle)
        print(f"[timer] FIRED: {label}")
        log_wake("timer_fired", query=label)
    except Exception:
        import traceback
        traceback.print_exc()


def schedule_timer(seconds, label, gui=None):
    """Fire `label` after `seconds`. Returns a human ETA string."""
    entry = {"label": label or "timer", "fire_at": time.time() + seconds,
             "gui": gui}
    with _timers_lock:
        _timers.append(entry)
    t = threading.Timer(seconds, _timer_fire, args=(entry, gui))
    t.daemon = True
    t.start()
    eta = (datetime.now() + timedelta(seconds=seconds)).strftime("%I:%M %p")
    log_wake("timer_set", query=label, rms=round(seconds, 1))
    return eta


def handle_local_timer(text, gui):
    """Intercept timer/reminder/alarm commands locally. Returns True if handled
    (caller should then skip the server round-trip)."""
    low = text.lower()
    # TIMER: relative duration
    if re.search(r"\btimer\b", low):
        secs = _parse_duration(low)
        if secs is None and re.search(r"\bfor\b", low):
            secs = _parse_duration(re.sub(r".*for", "for", low))
        if secs is None:
            if gui:
                gui.call(gui.set_reply, "For how long, sir?")
            return True
        label = "timer"
        mm = secs / 60
        if mm >= 1:
            label = f"timer · {mm:.0f} min"
        else:
            label = f"timer · {secs:.0f} sec"
        eta = schedule_timer(secs, label, gui)
        chime_think()
        if gui:
            gui.call(gui.set_reply, f"Timer set — {label}. Fires at {eta}.")
        return True
    # REMINDER: "remind me to X at <clock>" or "in <duration>"
    if re.search(r"remind me", low):
        secs = _parse_clock(low) or _parse_duration(low)
        # the thing to remember is the text between 'to'/'that' and 'at'/'in'
        m = re.search(r"remind me (?:to |that )(.+?)(?: at | in | by |$)",
                      low, re.S)
        thing = m.group(1).strip() if m else "reminder"
        if secs is None:
            if gui:
                gui.call(gui.set_reply, "When should I remind you, sir?")
            return True
        eta = schedule_timer(secs, f"reminder: {thing}", gui)
        chime_think()
        if gui:
            gui.call(gui.set_reply, f"Reminder set — “{thing}”. At {eta}.")
        return True
    # ALARM / WAKE: "wake me at 7am" / "alarm 6:30"
    if re.search(r"\b(wake me|alarm)\b", low):
        secs = _parse_clock(low)
        if secs is None:
            if gui:
                gui.call(gui.set_reply, "What time, sir?")
            return True
        eta = schedule_timer(secs, "alarm", gui)
        chime_think()
        if gui:
            gui.call(gui.set_reply, f"Alarm set for {eta}.")
        return True
    return False


# ═══════════════════════════════════════════════════════════════════
# Main loop
# ═══════════════════════════════════════════════════════════════════
def handle_query(text, gui, with_video):
    low = text.lower()
    # local agentic intents FIRST — they don't need the server (privacy + speed)
    if handle_local_timer(text, gui):
        log_wake("response", query=text, intent="local_timer")
        return
    if "youtube" in low or low.startswith("play "):
        ok = play_youtube(text, with_video=with_video, gui=gui)
        log_wake("youtube", query=text, resolved=ok)
        if not ok and gui:
            gui.call(gui.set_reply, "Sorry, I couldn't find that on YouTube.")
        return
    # normal chat
    if gui:
        gui.call(gui.set_thinking)
        chime_think()
    data = lc.chat(lc.DEFAULT_URL, text, play=True, source="jeeves_speaker")
    _audio_guard()          # duck the mic while our spoken reply plays
    log_wake("response", query=text, intent=data.get("intent"),
             tier=data.get("tier"), response=data.get("text"))
    if gui:
        gui.call(gui.set_idle)


def run(monitor, gui, with_video):
    if gui:
        gui.call(gui.set_idle)
    print("Jeeves speaker online. Say ‘Hey Jeeves’. (Ctrl-C to quit)")
    while True:
        try:
            listen_for_wake(monitor, gui)
            chime_wake()
            if gui:
                gui.call(gui.set_listening)
            # Enter a conversation: capture the first command, respond, then
            # keep listening for follow-ups (no need to repeat 'hey jeeves')
            # until an exit phrase or idle timeout.
            conversation_loop(monitor, gui, with_video)
        except KeyboardInterrupt:
            break
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            print(f"[loop error] {e}\n{tb}", file=sys.stderr)
            log_wake("loop_error", reason=str(e))
            if gui:
                gui.call(gui.set_reply, f"Error: {e}")
                time.sleep(3)
                gui.call(gui.set_idle)


def main():
    p = argparse.ArgumentParser(description="Jeeves always-on smart speaker")
    p.add_argument("--no-gui", action="store_true", help="headless mode (default for daemon)")
    p.add_argument("--gui", action="store_true", help="show ambient fullscreen GUI (desktop session)")
    p.add_argument("--with-video", action="store_true", help="show YouTube video")
    p.add_argument("--no-audio", action="store_true", help="text only (no TTS)")
    p.add_argument("--server", default=lc.DEFAULT_URL)
    args = p.parse_args()

    # allow --no-audio / --server to propagate to linux_client
    if args.server != lc.DEFAULT_URL:
        lc.DEFAULT_URL = args.server
    if args.no_audio:
        lc.play_audio = lambda *a, **k: None

    # Only one Jeeves may own the mic at a time. The always-on daemon and a
    # --gui session must not both capture 'default' (they collide -> the
    # second gets silence and never wakes). Bail out with a clear message.
    if not acquire_mic_lock():
        sys.exit(2)

    # One continuous mic monitor owns the microphone (meter + wake + query).
    monitor = MicMonitor()
    monitor.start()

    # Default to headless (always-on daemon). GUI only when explicitly --gui
    # and a display is available (avoids Tk crashes under systemd/no-session).
    gui = None
    use_gui = args.gui and (os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"))
    if use_gui:
        root = tk.Tk()
        gui = AmbientGUI(root)
        gui.attach(monitor)
        t = threading.Thread(target=run, args=(monitor, gui, args.with_video),
                             daemon=True)
        t.start()
        try:
            root.mainloop()
        finally:
            monitor.stop()
            try:
                os.unlink(MIC_LOCK)
            except OSError:
                pass
    else:
        try:
            run(monitor, None, args.with_video)
        finally:
            monitor.stop()
            try:
                os.unlink(MIC_LOCK)
            except OSError:
                pass


if __name__ == "__main__":
    main()
