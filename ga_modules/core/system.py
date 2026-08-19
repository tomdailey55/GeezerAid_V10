"""
GeezerAid — Main System

Wires all modules together:
  - Event bus (communication)
  - State manager (session + device + household)
  - Coordinator (routing)
  - HA bridge (smart home)
  - Perceive (STT + wake word)
  - Cognize (LLM routing)
  - Action (TTS + display)
  - Knowledge (vault search)
  - Sync engine (CRDT)
  - Discovery (mDNS)
"""
import logging
import time
from pathlib import Path
from typing import Optional

from ga_modules.core import EventBus, get_event_bus
from ga_modules.core.state_manager import StateManager
from ga_modules.core.coordinator import Coordinator, Response
from ga_modules.core.ha_bridge import HABridge, SafetyLayer
from ga_modules.core.sync_engine import SyncEngine
from ga_modules.core.discovery import DeviceDiscovery
from ga_modules.modules.perceive import PerceiveModule
from ga_modules.modules.cognize import CognizeModule
from ga_modules.modules.action import ActionModule
from ga_modules.modules.knowledge import KnowledgeModule

logger = logging.getLogger(__name__)


class GeezerAid:
    """The main GA system."""

    def __init__(self, device_id: str, device_type: str = "gtv",
                 vault_path: Optional[str] = None,
                 ha_url: Optional[str] = None,
                 ha_token: Optional[str] = None):
        self.device_id = device_id
        self.device_type = device_type

        # Core
        self.bus = get_event_bus()
        self.state = StateManager(device_id, self.bus)
        self.coordinator = Coordinator(device_id, device_type, self.bus, self.state)

        # Bridges
        self.ha = HABridge(ha_url, ha_token or "", self.bus) if ha_url else None
        self.safety = SafetyLayer()
        self.sync = SyncEngine(device_id, self.bus)
        self.discovery = DeviceDiscovery(device_id, self.bus)

        # Modules
        self.perceive = PerceiveModule()
        self.cognize = CognizeModule()
        self.action = ActionModule()
        self.knowledge = KnowledgeModule(vault_path)

        # Wire everything
        self._wire()

    def _wire(self):
        """Wire modules together."""
        # Register modules with coordinator
        self.coordinator.register_module("stt", self.perceive)
        self.coordinator.register_module("llm", self.cognize)
        self.coordinator.register_module("tts", self.action)
        self.coordinator.register_module("display", self.action)
        self.coordinator.register_module("knowledge", self.knowledge)

        # Set bridges
        if self.ha:
            self.coordinator.set_ha_bridge(self.ha)
        self.coordinator.set_safety_layer(self.safety)

        # Subscribe to events
        self.bus.subscribe("ga.wake.detected", self._on_wake)
        self.bus.subscribe("ga.command.received", self._on_command)
        self.bus.subscribe("ga.response.ready", self._on_response)

    def start(self):
        """Start the system."""
        self.sync.start()
        logger.info(f"GeezerAid started on {self.device_id}")

    def stop(self):
        """Stop the system."""
        self.sync.stop()
        logger.info(f"GeezerAid stopped on {self.device_id}")

    # ============================================================
    # Event handlers
    # ============================================================

    def _on_wake(self, msg):
        """Handle wake word."""
        user = msg["payload"].get("user", "unknown")
        self.state.start_session(user, self.device_id)
        logger.info(f"Wake word detected by {user}")

    def _on_command(self, msg):
        """Handle command."""
        command = msg["payload"].get("text", "")
        if not command:
            return

        self.state.add_to_history("user", command)
        context = self.state.get_context()
        response = self.coordinator.route_command(command, context)
        self.state.add_to_history("assistant", response.text)

        self.bus.publish("ga.response.ready", {
            "device_id": self.device_id,
            "text": response.text,
            "summary": response.summary,
            "source": response.source,
        })

    def _on_response(self, msg):
        """Handle response."""
        text = msg["payload"].get("text", "")
        if text and "tts" in self.coordinator.modules:
            voice = self.coordinator.select_tts_voice(
                self.state.get_current_user() or "unknown"
            )
            audio = self.action.speak(text, voice)
            if audio:
                self.action.play_audio(audio)

    # ============================================================
    # Capabilities
    # ============================================================

    @property
    def capabilities(self) -> list[str]:
        """List all capabilities."""
        caps = []
        for module in [self.perceive, self.cognize, self.action, self.knowledge]:
            caps.extend(module.capabilities)
        return list(set(caps))

    @property
    def available(self) -> bool:
        """Check if system is available."""
        return any([
            self.perceive.available,
            self.cognize.available,
            self.action.available,
            self.knowledge.available,
        ])
