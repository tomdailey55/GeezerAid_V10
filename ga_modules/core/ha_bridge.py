"""
GeezerAid — Home Assistant Bridge

Bridge between GA and Home Assistant. Provides:
  - Intent matching (fast path for common commands)
  - Service calling (entity control)
  - Tool calling (LLM-driven device control)
  - Safety integration

Stolen from: HA's prefer_local_intents + conversation agent + entity model
Replaces: nothing (we had no smart home integration)
"""
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class Intent:
    """A matched command pattern."""
    service: str
    entity: Optional[str] = None
    value: Optional[str] = None
    params: dict = field(default_factory=dict)


@dataclass
class Tool:
    """An available LLM tool (HA service)."""
    name: str
    description: str
    parameters: dict = field(default_factory=dict)
    entity_id: Optional[str] = None


@dataclass
class Entity:
    """An HA entity."""
    entity_id: str
    domain: str
    state: str
    attributes: dict = field(default_factory=dict)
    services: list[str] = field(default_factory=list)


class HABridge:
    """Bridge to Home Assistant."""

    # Built-in command patterns (stolen from HA's voice intents)
    BUILTIN_PATTERNS = [
        (r"turn on (the )?(?P<entity>.+)", "homeassistant.turn_on"),
        (r"turn off (the )?(?P<entity>.+)", "homeassistant.turn_off"),
        (r"set (?P<entity>.+) to (?P<value>.+)", "homeassistant.set_value"),
        (r"dim (the )?(?P<entity>.+) to (?P<value>\d+)", "light.set_brightness"),
        (r"(?P<entity>.+) (is|are) (on|off)", "homeassistant.get_state"),
        (r"lock (the )?(?P<entity>.+)", "lock.lock"),
        (r"unlock (the )?(?P<entity>.+)", "lock.unlock"),
        (r"set (the )?thermostat to (?P<value>\d+)", "climate.set_temperature"),
        (r"what('s| is) the temperature", "sensor.get_temperature"),
        (r"who('s| is) (home|here|in (?P<room>.+))", "household.get_occupancy"),
        (r"what time is it", "household.get_time"),
        (r"what('s| is) the weather", "household.get_weather"),
    ]

    def __init__(self, ha_url: Optional[str] = None, token: Optional[str] = None, event_bus=None):
        self.ha_url = ha_url or "http://localhost:8123"
        self.token = token or ""
        self.bus = event_bus
        self.entities: dict[str, Entity] = {}
        self._intents = self._build_intents()

    def _build_intents(self) -> list[tuple[re.Pattern, str]]:
        """Compile regex patterns."""
        return [(re.compile(p, re.I), svc) for p, svc in self.BUILTIN_PATTERNS]

    # ============================================================
    # Intent Matching (stolen from HA's prefer_local_intents)
    # ============================================================

    def match_intent(self, command: str) -> Optional[Intent]:
        """Try to match a built-in intent."""
        for pattern, service in self._intents:
            m = pattern.match(command.lower())
            if m:
                return Intent(
                    service=service,
                    entity=m.group("entity") if "entity" in m.groupdict() else None,
                    value=m.group("value") if "value" in m.groupdict() else None,
                    params=m.groupdict(),
                )
        return None

    # ============================================================
    # Service Calling (stolen from HA's service model)
    # ============================================================

    def call_service(self, service: str, entity_id: Optional[str] = None, **params) -> dict:
        """Call an HA service."""
        domain, action = service.split(".")
        
        # In real impl: POST /api/services/{domain}/{action}
        # For now, return a mock result
        result = {
            "service": service,
            "entity_id": entity_id,
            "params": params,
            "success": True,
        }
        
        if self.bus:
            self.bus.publish("ga.device.state", {
                "entity_id": entity_id,
                "service": service,
                "result": result,
            })
        
        return result

    # ============================================================
    # Tool Calling (stolen from HA's conversation agent)
    # ============================================================

    def can_control(self, command: str) -> bool:
        """Check if HA can control something in this command."""
        return self._extract_entity(command) is not None

    def available_tools(self) -> list[Tool]:
        """List available HA services as LLM tools."""
        tools = []
        for entity_id, entity in self.entities.items():
            for service in entity.services:
                tools.append(Tool(
                    name=f"{entity.domain}.{service}",
                    description=f"{service} {entity_id}",
                    parameters={"entity_id": {"type": "string", "default": entity_id}},
                    entity_id=entity_id,
                ))
        return tools

    def _extract_entity(self, command: str) -> Optional[str]:
        """Extract entity name from command."""
        # Simple extraction: look for known entity names
        words = command.lower().split()
        for entity_id in self.entities:
            if entity_id.split(".")[-1].lower() in words:
                return entity_id
        return None

    # ============================================================
    # Entity Management
    # ============================================================

    def sync_entities(self):
        """Sync entity states from HA."""
        # In real impl: GET /api/states
        pass

    def add_entity(self, entity: Entity):
        """Add an entity to the registry."""
        self.entities[entity.entity_id] = entity


class SafetyLayer:
    """Prevent dangerous actions."""

    DEFAULT_RULES = [
        {"pattern": r"turn off.*server", "action": "block", "reason": "Server power"},
        {"pattern": r"turn off.*water heater", "action": "block", "reason": "Water heater"},
        {"pattern": r"turn off.*network", "action": "block", "reason": "Network security"},
        {"pattern": r"turn off.*adguard", "action": "block", "reason": "Security"},
        {"pattern": r"turn off.*office", "action": "ask", "reason": "Only lights, not switches"},
    ]

    def __init__(self):
        self.rules = []
        for rule in self.DEFAULT_RULES:
            self.rules.append({
                "pattern": re.compile(rule["pattern"], re.I),
                "action": rule["action"],
                "reason": rule["reason"],
            })

    def is_dangerous(self, command: str, entity: Optional[str] = None) -> bool:
        """Check if a command is dangerous."""
        for rule in self.rules:
            if rule["pattern"].match(command):
                return rule["action"] == "block"
        return False
