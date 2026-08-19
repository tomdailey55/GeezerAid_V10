"""
GeezerAid — Hermes Integration

Registers ga_modules as Hermes tools/skills.
This is the bridge between Hermes Agent and the GA module system.

Real path: Hermes skills are SKILL.md files in ~/.hermes/skills/
This integration creates the skill that drives GA.
"""
import logging
import os
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class HermesGAIntegration:
    """Integrate ga_modules with Hermes Agent."""

    def __init__(self, ga_system: Any):
        self.ga = ga_system
        self._tools = {}

    def register_tools(self):
        """Register GA tools with Hermes."""
        self._tools = {
            "ga_perceive_transcribe": self._tool_transcribe,
            "ga_perceive_wake": self._tool_wake_word,
            "ga_cognize_generate": self._tool_generate,
            "ga_action_speak": self._tool_speak,
            "ga_action_display": self._tool_display,
            "ga_knowledge_answer": self._tool_answer,
            "ga_ha_intent": self._tool_intent,
            "ga_ha_service": self._tool_service,
            "ga_state_session": self._tool_session,
            "ga_state_occupancy": self._tool_occupancy,
        }
        return self._tools

    # ============================================================
    # Tool implementations
    # ============================================================

    def _tool_transcribe(self, audio_path: str) -> str:
        """Transcribe audio file."""
        if "stt" not in self.ga.coordinator.modules:
            return "No STT module"
        result = self.ga.coordinator.modules["stt"].transcribe_file(audio_path)
        return result or "Transcription failed"

    def _tool_wake_word(self, text: str, wake_words: Optional[list] = None) -> bool:
        """Check for wake word."""
        if "stt" not in self.ga.coordinator.modules:
            return False
        return self.ga.coordinator.modules["stt"].detect_wake_word(text, wake_words)

    def _tool_generate(self, prompt: str) -> str:
        """Generate LLM response."""
        if "llm" not in self.ga.coordinator.modules:
            return "No LLM module"
        context = self.ga.state.get_context()
        result = self.ga.coordinator.modules["llm"].generate(prompt, context)
        return result.text if result else "Generation failed"

    def _tool_speak(self, text: str, voice: Optional[str] = None) -> str:
        """Speak text."""
        if "tts" not in self.ga.coordinator.modules:
            return "No TTS module"
        voice = voice or self.ga.coordinator.select_tts_voice(
            self.ga.state.get_current_user() or "unknown"
        )
        audio = self.ga.coordinator.modules["tts"].speak(text, voice)
        if audio:
            self.ga.coordinator.modules["tts"].play_audio(audio)
            return f"Spoke: {text[:50]}..."
        return "TTS failed"

    def _tool_display(self, text: str, target: Optional[str] = None) -> str:
        """Show text on display."""
        if "display" not in self.ga.coordinator.modules:
            return "No display module"
        target = target or "bottom"
        self.ga.coordinator.modules["display"].show_text(text, target)
        return f"Displayed on {target}: {text[:50]}..."

    def _tool_answer(self, query: str) -> str:
        """Answer from knowledge."""
        if "knowledge" not in self.ga.coordinator.modules:
            return "No knowledge module"
        result = self.ga.coordinator.modules["knowledge"].answer(query)
        return result or "No answer found"

    def _tool_intent(self, command: str) -> dict:
        """Match HA intent."""
        if not self.ga.ha:
            return {"error": "No HA bridge"}
        intent = self.ga.ha.match_intent(command)
        if intent:
            return {"service": intent.service, "entity": intent.entity, "value": intent.value}
        return {"matched": False}

    def _tool_service(self, service: str, entity_id: Optional[str] = None, **params) -> dict:
        """Call HA service."""
        if not self.ga.ha:
            return {"error": "No HA bridge"}
        return self.ga.ha.call_service(service, entity_id, **params)

    def _tool_session(self, user: str, device_id: Optional[str] = None) -> dict:
        """Start session."""
        self.ga.state.start_session(user, device_id)
        return {"user": user, "room": self.ga.state.session.get("room")}

    def _tool_occupancy(self, room: Optional[str] = None, user: Optional[str] = None) -> dict:
        """Get/set occupancy."""
        if room and user:
            self.ga.state.set_occupancy(room, user)
        return self.ga.state.get_occupancy()


# ============================================================
# Hermes skill entry point
# ============================================================

def create_ga_skill(ga_system: Any) -> dict:
    """Create Hermes skill definition for GA."""
    integration = HermesGAIntegration(ga_system)
    tools = integration.register_tools()

    return {
        "name": "ga-v8-modular",
        "description": "Drive GeezerAid's modular AI household system",
        "tools": {
            name: {"handler": func, "description": func.__doc__}
            for name, func in tools.items()
        },
    }
