#!/usr/bin/env python3
"""GENIUS TV GUI — QtQuick ambient main screen for the GA-Linux client.

Implements the SAME interface as AmbientGUI (attach, call, set_idle,
set_listening, set_thinking, set_reply, set_playing, set_transcript) so it can
be swapped into jeeves_speaker.py without changing the wake/respond loop.

Drives ga_main.qml: full-bleed old-master art backdrop, digital clock + date +
weather in an inline bottom bar, quiet voice-state dot + caption.

Threading: QApplication must run on the main thread. The wake/respond loop runs
in a background thread and calls gui.call(...) — we enqueue to a queue and a
main-thread QTimer drains it (same pattern as AmbientGUI's queue).
"""
import sys, os, queue, threading, math, time
from datetime import datetime

import os
from PySide6.QtCore import QObject, Signal, Slot, QTimer, QUrl

# Real weather for the bar. Same source server_v9.py uses for spoken answers,
# so the screen and Jeeves cannot disagree.
GTV_WEATHER_LOCATION = os.getenv("GA_WEATHER_LOCATION", "Sarasota,FL")


def _fetch_weather():
    """Return (summary, detail) from wttr.in, or (None, None) on any failure.

    Never invents or reuses stale values — the caller shows an em-dash instead,
    because a wrong temperature on a household display is worse than none.
    """
    import urllib.parse
    import urllib.request
    loc = urllib.parse.quote(GTV_WEATHER_LOCATION)
    try:
        # %C=condition %t=temp %f=feels-like %h=humidity
        url = f"https://wttr.in/{loc}?format=%C|%t|%f|%h"
        req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
        with urllib.request.urlopen(req, timeout=8) as r:
            raw = r.read().decode("utf-8", "replace").strip()
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) < 4 or not parts[1]:
            return None, None
        cond, temp, feels, hum = parts[0], parts[1], parts[2], parts[3]
        temp = temp.lstrip("+")
        feels = feels.lstrip("+")
        summary = f"{temp} \u00b7 {cond}"
        # Only mention feels-like when it genuinely differs — otherwise noise.
        detail = f"Feels like {feels}" if feels != temp else f"Humidity {hum}"
        return summary, detail
    except Exception:
        return None, None
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

# Path to the QML (relative to this file's dir)
_HERE = os.path.dirname(os.path.abspath(__file__))
_QML = os.path.join(_HERE, "ga_main.qml")


class _Backend(QObject):
    """Exposes signals the QML binds to."""
    clockChanged = Signal(str)
    dateChanged = Signal(str)
    stateChanged = Signal(str)
    captionChanged = Signal(str)
    transcriptChanged = Signal(str)
    weatherChanged = Signal(str)
    weatherDetailChanged = Signal(str)
    calendarChanged = Signal(str)
    suggestionChanged = Signal(str)
    nowPlayingChanged = Signal(str)
    micLevelChanged = Signal(float)
    hourAngleChanged = Signal(float)
    minuteAngleChanged = Signal(float)
    secondAngleChanged = Signal(float)

    def __init__(self):
        super().__init__()
        self._state = "idle"
        self._mic = 0.0
        self._clock_timer = QTimer()
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start(1000)
        self._mic_timer = QTimer()
        self._mic_timer.timeout.connect(self._tick_mic)
        self._mic_timer.start(100)
        # Real weather: refresh every 10 min (wttr.in caches, so this is polite).
        self._weather_timer = QTimer()
        self._weather_timer.timeout.connect(self._tick_weather)
        self._weather_timer.start(600000)
        QTimer.singleShot(2000, self._tick_weather)   # populate soon after boot

    def _tick_clock(self):
        now = datetime.now()
        self.clockChanged.emit(now.strftime("%I:%M"))
        self.dateChanged.emit(now.strftime("%A, %B %d"))
        sec = now.second + now.microsecond / 1e6
        minute = now.minute + sec / 60.0
        hour = (now.hour % 12) + minute / 60.0
        self.secondAngleChanged.emit(sec * 6.0)
        self.minuteAngleChanged.emit(minute * 6.0)
        self.hourAngleChanged.emit(hour * 30.0)

    def _tick_mic(self):
        # subtle idle breathing — calm, not a visualizer
        self._mic = 0.05 + 0.02 * math.sin(time.time() * 1.5)
        self.micLevelChanged.emit(self._mic)

    @Slot(str)
    def setState(self, s):
        self._state = s
        self.stateChanged.emit(s)
        labels = {
            "idle": "",
            "listening": "Listening…",
            "thinking": "Thinking…",
            "reply": "Speaking…",
            "playing": "Playing…",
        }
        self.captionChanged.emit(labels.get(s, s))

    @Slot(str)
    def setTranscript(self, t):
        self.transcriptChanged.emit(t)

    def _tick_weather(self):
        """Refresh the bar's weather. Runs the network call on a worker thread
        so a slow or hanging request cannot stall the ambient display."""
        import threading

        def work():
            summary, detail = _fetch_weather()
            if summary:
                self.weatherChanged.emit(summary)
                self.weatherDetailChanged.emit(detail or "")
            else:
                # Be honest rather than plausible.
                self.weatherChanged.emit("\u2014")
                self.weatherDetailChanged.emit("weather unavailable")

        threading.Thread(target=work, daemon=True).start()

    @Slot(str)
    def setWeather(self, w):
        self.weatherChanged.emit(w)

    @Slot(str)
    def setWeatherDetail(self, d):
        self.weatherDetailChanged.emit(d)

    @Slot()
    def refreshWeather(self):
        """Re-fetch weather — called by QML when the bar migrates."""
        self._tick_weather()

    @Slot(str)
    def setCalendar(self, c):
        self.calendarChanged.emit(c)

    @Slot(str)
    def setSuggestion(self, s):
        self.suggestionChanged.emit(s)

    @Slot(str)
    def setNowPlaying(self, t):
        self.nowPlayingChanged.emit(t)


class GeniusTVGUI:
    """QtQuick ambient GUI — drop-in replacement for AmbientGUI."""

    def __init__(self, app=None):
        self.app = app or QGuiApplication(sys.argv)
        self.engine = QQmlApplicationEngine()
        self.backend = _Backend()
        self.engine.rootContext().setContextProperty("backend", self.backend)
        self.engine.load(QUrl.fromLocalFile(_QML))
        if not self.engine.rootObjects():
            raise RuntimeError("Genius TV QML failed to load")
        self.root = self.engine.rootObjects()[0]

        # bind backend signals -> QML properties
        self.backend.hourAngleChanged.connect(lambda v: self.root.setProperty("hourAngle", v))
        self.backend.minuteAngleChanged.connect(lambda v: self.root.setProperty("minuteAngle", v))
        self.backend.secondAngleChanged.connect(lambda v: self.root.setProperty("secondAngle", v))
        self.backend.clockChanged.connect(lambda v: self.root.setProperty("clockText", v))
        self.backend.dateChanged.connect(lambda v: self.root.setProperty("dateText", v))
        self.backend.stateChanged.connect(lambda v: self.root.setProperty("stateText", v))
        self.backend.captionChanged.connect(lambda v: self.root.setProperty("captionText", v))
        self.backend.transcriptChanged.connect(lambda v: self.root.setProperty("transcriptText", v))
        self.backend.weatherChanged.connect(lambda v: self.root.setProperty("weatherText", v))
        self.backend.weatherDetailChanged.connect(lambda v: self.root.setProperty("weatherDetail", v))
        self.backend.calendarChanged.connect(lambda v: self.root.setProperty("calendarText", v))
        self.backend.suggestionChanged.connect(lambda v: self.root.setProperty("suggestionText", v))
        self.backend.nowPlayingChanged.connect(lambda v: self.root.setProperty("nowPlayingText", v))
        self.backend.micLevelChanged.connect(lambda v: self.root.setProperty("micLevel", v))

        # thread-safe dispatch queue (bg thread -> main thread)
        self._q = queue.Queue()
        self._drain_timer = QTimer()
        self._drain_timer.timeout.connect(self._drain)
        self._drain_timer.start(40)

        self.monitor = None

    # ── thread-safe dispatch (same contract as AmbientGUI.call) ──
    def call(self, fn, *a):
        self._q.put((fn, a))

    def _drain(self):
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

    def attach(self, monitor):
        self.monitor = monitor

    # ── state setters (same contract as AmbientGUI) ──
    def set_idle(self):
        self.backend.setState("idle")

    def set_listening(self):
        self.backend.setState("listening")

    def set_thinking(self):
        self.backend.setState("thinking")

    def set_reply(self, text):
        self.backend.setState("reply")
        self.backend.setTranscript(text)

    def set_playing(self, title):
        self.backend.setState("playing")
        self.backend.setNowPlaying(title)

    def set_transcript(self, text):
        self.backend.setTranscript(text)

    # ── Qt event loop ──
    def mainloop(self):
        return self.app.exec()


def main():
    """Standalone run (for testing the GUI without the voice loop)."""
    gui = GeniusTVGUI()
    sys.exit(gui.mainloop())


if __name__ == "__main__":
    main()
