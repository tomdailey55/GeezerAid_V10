"""
Tests for the Action Module.
"""
import pytest
from ga_modules.modules.action import ActionModule


class TestActionModule:
    def setup_method(self):
        self.action = ActionModule(tts_engine="kokoro")

    def test_speak_returns_bytes(self):
        """Speak returns audio bytes."""
        audio = self.action.speak("Hello world")
        assert audio is not None
        assert isinstance(audio, bytes)

    def test_speak_empty_text(self):
        """Empty text returns None."""
        assert self.action.speak("") is None

    def test_show_text(self):
        """Show text updates display state."""
        self.action.show_text("Hello", target="bottom")
        assert self.action.get_displayed_text("bottom") == "Hello"

    def test_show_image(self):
        """Show image updates display state."""
        self.action.show_image("/tmp/test.jpg")
        assert self.action.get_displayed_text("image") == "/tmp/test.jpg"

    def test_clear_display_target(self):
        """Clear specific target."""
        self.action.show_text("Hello", target="bottom")
        self.action.clear_display("bottom")
        assert self.action.get_displayed_text("bottom") is None

    def test_clear_display_all(self):
        """Clear all targets."""
        self.action.show_text("Hello", target="bottom")
        self.action.show_text("World", target="top")
        self.action.clear_display()
        assert self.action.get_displayed_text("bottom") is None
        assert self.action.get_displayed_text("top") is None

    def test_capabilities(self):
        """Capabilities list."""
        caps = self.action.capabilities
        assert "tts" in caps
        assert "display" in caps

    def test_available(self):
        """Available check."""
        assert self.action.available is True

    def test_edge_tts(self):
        """Edge TTS engine."""
        action = ActionModule(tts_engine="edge")
        audio = action.speak("Hello")
        assert audio is not None

    def test_unknown_engine(self):
        """Unknown engine returns None."""
        action = ActionModule(tts_engine="unknown")
        assert action.speak("Hello") is None
        assert action.available is False
