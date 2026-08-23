"""
GeezerAid Persona Registry — wake-word = identity.

Maps a wake word / persona name to the user, TTS voice, and persona prompt.
The wake word IS the user identity: "Hey Jeeves" -> Tom, "Hey Circe" -> Andrea,
any other defined persona -> that user. Once a persona is active, GA keeps
talking to that same person until a different "Hey <name>" is received.

This is device-agnostic by construction: the same tablet/TV/phone serves
whichever user speaks, because identity travels with the voice, not the device.

NOTE: This lives in GA-V9/tools because the V10 server (server/server_v9.py)
imports its helper modules from ~/Public/GA-V9/tools. It is the V10 persona
layer; the GA-V9 tree itself is not the deployment target.
"""
import os
import json
from pathlib import Path

# ── Persona definitions ──
# Each persona: user, tts_voice (Kokoro voice name), and the persona prompt
# fragment used to build the system prompt. Add new personas here.
PERSONAS = {
    "jeeves": {
        "user": "Tom",
        "title": "sir",
        "tts_voice": os.getenv("GA_TTS_VOICE", "bm_lewis"),
        "persona": "Jeeves, a refined British valet",
        "wake_words": ["hey jeeves", "hello jeeves", "jeeves"],
    },
    "circe": {
        "user": "Andrea",
        "title": "dear",
        "tts_voice": os.getenv("GA_TTS_VOICE_CIRCE", "af_amy"),
        "persona": "Circe, a warm and attentive companion",
        "wake_words": ["hey circe", "hello circe", "circe"],
    },
}

# Optional: load extra personas from a JSON file so new users can be added
# without editing code. File: ~/.geeza/personas.json
_EXTRA = Path.home() / ".geeza" / "personas.json"
if _EXTRA.exists():
    try:
        _extra = json.loads(_EXTRA.read_text())
        for name, cfg in _extra.items():
            cfg.setdefault("wake_words", [f"hey {name}"])
            PERSONAS[name] = cfg
    except Exception:
        pass


class PersonaSession:
    """Tracks the active persona per device (sticky until a new wake word)."""

    def __init__(self):
        # device_id -> persona name
        self._active = {}

    def resolve(self, device_id: str, text: str) -> str:
        """Given a device and the spoken text, return the active persona name.

        If the text starts with a known wake word ("hey jeeves", "hey circe"),
        switch the device's active persona to that. Otherwise return the
        device's current (sticky) persona, defaulting to 'jeeves'.
        """
        lower = text.lower().strip()
        for name, cfg in PERSONAS.items():
            for ww in cfg["wake_words"]:
                if lower.startswith(ww) or lower == ww:
                    self._active[device_id] = name
                    return name
        # No wake word in this utterance — keep the sticky persona
        return self._active.get(device_id, "jeeves")

    def get(self, device_id: str) -> dict:
        """Return the persona config for a device's active persona."""
        name = self._active.get(device_id, "jeeves")
        return PERSONAS.get(name, PERSONAS["jeeves"])

    def active_name(self, device_id: str) -> str:
        return self._active.get(device_id, "jeeves")


# Singleton for the server
_session = PersonaSession()


def get_session() -> PersonaSession:
    return _session


def persona_for(device_id: str) -> dict:
    """Convenience: persona config for a device (defaults to Jeeves/Tom)."""
    return _session.get(device_id)
