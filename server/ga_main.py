#!/usr/bin/env python3
"""GENIUS TV — GA-Linux ambient main screen (QtQuick spike).
Drives ga_main.qml: clock, date, weather, calendar, voice state, transcript, suggestion.
Calm, premium, voice-first. No demo state-cycling — stays in idle unless driven.
"""
import sys, time, threading, math
from datetime import datetime
from PySide6.QtCore import QObject, Signal, Slot, QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine


class Backend(QObject):
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

        # clock tick
        self._clock_timer = QTimer()
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start(1000)

        # gentle idle mic pulse (so the dot breathes subtly)
        self._mic_timer = QTimer()
        self._mic_timer.timeout.connect(self._tick_mic)
        self._mic_timer.start(100)

    def _tick_clock(self):
        now = datetime.now()
        self.clockChanged.emit(now.strftime("%I:%M"))
        self.dateChanged.emit(now.strftime("%A, %B %d"))
        # analog hands (degrees, 12h clock)
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

    @Slot(str)
    def setWeather(self, w):
        self.weatherChanged.emit(w)

    @Slot(str)
    def setWeatherDetail(self, d):
        self.weatherDetailChanged.emit(d)

    @Slot(str)
    def setCalendar(self, c):
        self.calendarChanged.emit(c)

    @Slot(str)
    def setSuggestion(self, s):
        self.suggestionChanged.emit(s)

    @Slot(str)
    def setNowPlaying(self, t):
        self.nowPlayingChanged.emit(t)


def main():
    app = QGuiApplication(sys.argv)
    engine = QQmlApplicationEngine()
    backend = Backend()
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile("/home/tomdailey/mbp-public/GA-V9/ga_main.qml"))
    if not engine.rootObjects():
        sys.exit(1)
    root = engine.rootObjects()[0]
    # bind backend signals -> QML properties
    backend.hourAngleChanged.connect(lambda v: root.setProperty("hourAngle", v))
    backend.minuteAngleChanged.connect(lambda v: root.setProperty("minuteAngle", v))
    backend.secondAngleChanged.connect(lambda v: root.setProperty("secondAngle", v))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
