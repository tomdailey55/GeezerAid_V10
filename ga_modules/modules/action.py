"""
GeezerAid — Action Module

Text-to-speech + display control.
Wraps Kokoro TTS (already running on Strix) and the Chrome ambient display.

Real path: server_v9.py:293-303 (Kokoro TTS) + gtv_chrome server (display)
"""
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class ActionModule:
    """TTS + display control."""

    def __init__(self, tts_engine: str = "kokoro"):
        self.tts_engine = tts_engine
        self._display_state = {}

    # ============================================================
    # TTS (real: server_v9.py:KokoroTTS.generate)
    # ============================================================

    def speak(self, text: str, voice: str = "en_US-libritts-high") -> Optional[bytes]:
        """Generate speech from text.
        
        Args:
            text: Text to speak
            voice: Voice model name
            
        Returns: Audio bytes (WAV) or None
        """
        if not text:
            return None

        if self.tts_engine == "kokoro":
            return self._kokoro_generate(text, voice)
        elif self.tts_engine == "edge":
            return self._edge_generate(text, voice)
        else:
            logger.warning(f"Unknown TTS engine: {self.tts_engine}")
            return None

    def _kokoro_generate(self, text: str, voice: str) -> Optional[bytes]:
        """Generate speech using Kokoro TTS.
        
        Real: server_v9.py:293-303 uses KPipeline(lang_code='a')
        """
        try:
            # In real impl: from kokoro import KPipeline
            # pipe = KPipeline(lang_code="a")
            # audio = pipe(text, voice=voice)
            # For now, return a placeholder
            logger.info(f"Kokoro TTS: '{text[:50]}...' with voice {voice}")
            return b"FAKE_AUDIO_DATA"
        except Exception as e:
            logger.error(f"Kokoro TTS error: {e}")
            return None

    def _edge_generate(self, text: str, voice: str) -> Optional[bytes]:
        """Generate speech using Edge TTS (free, cloud)."""
        try:
            # In real impl: import edge_tts
            # communicate = edge_tts.Communicate(text, voice)
            # await communicate.save("/tmp/tts.mp3")
            logger.info(f"Edge TTS: '{text[:50]}...'")
            return b"FAKE_AUDIO_DATA"
        except Exception as e:
            logger.error(f"Edge TTS error: {e}")
            return None

    # ============================================================
    # Display Control (real: gtv_chrome server weather endpoint)
    # ============================================================

    def show_text(self, text: str, target: str = "bottom"):
        """Show text on display.
        
        Args:
            text: Text to display
            target: Where to show (bottom, top, center, weather, art_title)
        """
        self._display_state[target] = text
        logger.info(f"Display [{target}]: {text[:50]}...")

    def show_image(self, path: str):
        """Show image on display.
        
        Args:
            path: Path to image file
        """
        self._display_state["image"] = path
        logger.info(f"Display image: {path}")

    def get_displayed_text(self, target: Optional[str] = None) -> Optional[str]:
        """Get currently displayed text."""
        if target is None:
            return str(self._display_state)
        return self._display_state.get(target)

    def clear_display(self, target: str = None):
        """Clear display content."""
        if target:
            self._display_state.pop(target, None)
        else:
            self._display_state.clear()

    # ============================================================
    # Audio Playback
    # ============================================================

    def play_audio(self, audio: bytes):
        """Play audio through speakers.
        
        Real: aplay on Strix
        """
        if not audio:
            return
        
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as f:
            f.write(audio)
            f.flush()
            try:
                subprocess.run(
                    ["aplay", f.name],
                    capture_output=True,
                    timeout=30,
                )
            except Exception as e:
                logger.error(f"Audio playback error: {e}")

    # ============================================================
    # Capabilities
    # ============================================================

    @property
    def capabilities(self) -> list[str]:
        """List capabilities."""
        return ["tts", "display", "audio_playback"]

    @property
    def available(self) -> bool:
        """Check if TTS is available."""
        return self.tts_engine in ("kokoro", "edge")
