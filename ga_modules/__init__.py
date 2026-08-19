"""
GeezerAid Module Framework

Modules communicate via the event bus. Each module:
  - Has a standard interface (capabilities, available)
  - Publishes events to the bus
  - Subscribes to events it cares about
  - Is independently swappable

Stolen from: EdgeX Foundry device services + MQTT pub/sub
"""
from ga_modules.core import EventBus, get_event_bus
from ga_modules.core.state_manager import StateManager
from ga_modules.core.coordinator import Coordinator, Response
from ga_modules.core.ha_bridge import HABridge, Intent, Entity, Tool, SafetyLayer
