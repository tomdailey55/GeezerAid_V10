"""
GeezerAid — Perceive Module

Speech-to-text + wake word detection.
Wraps whisper.cpp (already running on Strix) with a clean interface.

Real path: jeeves_speaker.py:589 (_transcribe) + :644 (wake_detected)
"""
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class PerceiveModule:
    """STT + wake word detection using whisper.cpp."""

    def __init__(self, whisper_cli: str = None, model_path: str = None):
        self.whisper_cli = whisper_cli or os.getenv(
            "GA_WHISPER_CLI",
            str(Path.home() / "whisper.cpp/build/bin/whisper-cli"),
        )
        self.model_path = model_path or os.getenv(
            "GA_WHISPER_GGUF",
            str(Path.home() / "whisper.cpp/models/ggml-large-v3.bin"),
        )
        self._check_binary()

    def _check_binary(self):
        """Verify whisper.cpp binary exists."""
        if not Path(self.whisper_cli).exists():
            logger.warning(f"whisper-cli not found at {self.whisper_cli}")
        if not Path(self.model_path).exists():
            logger.warning(f"whisper model not found at {self.model_path}")

    # ============================================================
    # Transcription (real: jeeves_speaker.py:_transcribe)
    # ============================================================

    def transcribe(self, audio: bytes, language: str = "en") -> Optional[str]:
        """Transcribe audio to text.
        
        Args:
            audio: Raw PCM bytes (16kHz, 16-bit, mono)
            language: Language code
            
        Returns: Transcribed text or None
        """
        if not audio:
            return None

        # Write audio to temp file (whisper-cli reads from file)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as f:
            f.write(audio)
            f.flush()
            return self.transcribe_file(f.name, language)

    def transcribe_file(self, wav_path: str, language: str = "en") -> Optional[str]:
        """Transcribe a WAV file."""
        try:
            result = subprocess.run(
                [
                    self.whisper_cli,
                    "-f", wav_path,
                    "-m", self.model_path,
                    "--output-txt",
                    "-l", language,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                return result.stdout.strip()
            logger.warning(f"whisper-cli failed: {result.stderr}")
        except Exception as e:
            logger.error(f"Transcription error: {e}")
        return None

    # ============================================================
    # Wake Word Detection (real: jeeves_speaker.py:wake_detected)
    # ============================================================

    def detect_wake_word(self, text: Optional[str], wake_words: Optional[list[str]] = None) -> bool:
        """Check if text contains a wake word.
        
        Args:
            text: Transcribed text
            wake_words: List of wake words (default: ["hey jeeves"])
            
        Returns: True if wake word detected
        """
        if not text:
            return False
        
        wake_words = wake_words or ["hey jeeves"]
        text_lower = text.lower()
        
        for word in wake_words:
            if word.lower() in text_lower:
                logger.info(f"Wake word detected: {word}")
                return True
        return False

    def extract_command(self, text: str, wake_words: list[str] = None) -> Optional[str]:
        """Extract command after wake word.
        
        Args:
            text: Full transcribed text
            wake_words: List of wake words
            
        Returns: Command text (without wake word) or None
        """
        if not text:
            return None
        
        wake_words = wake_words or ["hey jeeves"]
        text_lower = text.lower()
        
        for word in wake_words:
            idx = text_lower.find(word.lower())
            if idx != -1:
                # Return text after wake word
                command = text[idx + len(word):].strip()
                # Remove leading punctuation
                command = command.lstrip(",.!? ")
                return command if command else None
        return None

    # ============================================================
    # Capabilities
    # ============================================================

    @property
    def capabilities(self) -> list[str]:
        """List capabilities."""
        return ["stt", "wake_word"]

    @property
    def available(self) -> bool:
        """Check if whisper.cpp is available."""
        return Path(self.whisper_cli).exists() and Path(self.model_path).exists()
