"""
Tests for the Perceive Module.
"""
import pytest
from unittest.mock import patch, MagicMock
from ga_modules.modules.perceive import PerceiveModule


class TestPerceiveModule:
    def setup_method(self):
        self.perceive = PerceiveModule(
            whisper_cli="/usr/bin/true",  # dummy
            model_path="/tmp/model.bin",
        )

    def test_detect_wake_word_default(self):
        """Default wake word detection."""
        assert self.perceive.detect_wake_word("hey jeeves, turn on the lights") is True
        assert self.perceive.detect_wake_word("turn on the lights") is False

    def test_detect_wake_word_custom(self):
        """Custom wake words."""
        assert self.perceive.detect_wake_word("hey andrea", ["hey andrea"]) is True
        assert self.perceive.detect_wake_word("hey jeeves", ["hey andrea"]) is False

    def test_detect_wake_word_case_insensitive(self):
        """Case insensitive matching."""
        assert self.perceive.detect_wake_word("HEY JEEVES") is True
        assert self.perceive.detect_wake_word("Hey Jeeves") is True

    def test_detect_wake_word_empty(self):
        """Empty text returns False."""
        assert self.perceive.detect_wake_word("") is False
        assert self.perceive.detect_wake_word(None) is False

    def test_extract_command(self):
        """Command extraction after wake word."""
        cmd = self.perceive.extract_command("hey jeeves, turn on the lights")
        assert cmd == "turn on the lights"

    def test_extract_command_no_wake(self):
        """No wake word returns None."""
        cmd = self.perceive.extract_command("turn on the lights")
        assert cmd is None

    def test_extract_command_trailing_punctuation(self):
        """Strips leading punctuation."""
        cmd = self.perceive.extract_command("hey jeeves, turn on the lights")
        assert cmd == "turn on the lights"
        cmd = self.perceive.extract_command("hey jeeves! turn on the lights")
        assert cmd == "turn on the lights"

    def test_capabilities(self):
        """Capabilities list."""
        caps = self.perceive.capabilities
        assert "stt" in caps
        assert "wake_word" in caps

    def test_available_false_when_missing(self):
        """Available false when binary missing."""
        p = PerceiveModule(whisper_cli="/nonexistent", model_path="/nonexistent")
        assert p.available is False

    @patch("subprocess.run")
    def test_transcribe_file(self, mock_run):
        """Transcription calls whisper-cli."""
        mock_run.return_value = MagicMock(returncode=0, stdout="Hello world\n")
        
        result = self.perceive.transcribe_file("/tmp/test.wav")
        
        assert result == "Hello world"
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "-f" in args
        assert "/tmp/test.wav" in args

    @patch("subprocess.run")
    def test_transcribe_file_failure(self, mock_run):
        """Transcription failure returns None."""
        mock_run.return_value = MagicMock(returncode=1, stderr="error")
        
        result = self.perceive.transcribe_file("/tmp/test.wav")
        assert result is None

    def test_transcribe_empty_audio(self):
        """Empty audio returns None."""
        result = self.perceive.transcribe(b"")
        assert result is None
