"""
GeezerAid — Coordinator

The routing brain. Decides which module handles each command based on policy.

Routing priority:
  1. Safety check (block dangerous actions)
  2. HA built-in intents ("turn on lights" → 200ms, no LLM)
  3. GA local knowledge (recipes, calendar, preferences)
  4. HA tool calling (device control via LLM)
  5. Local LLM (fast, private)
  6. Cloud LLM backup (complex queries)

Stolen from: HA's prefer_local_intents + server_v9.py multi-backend routing
Replaces: hardcoded routing in server_v9.py (one big if-else chain)
"""
import logging
import time
from typing import Any, Optional

from ga_modules.core.data_flywheel import InteractionLogger, EvalDataset, CostTracker, Interaction, patch_coordinator

from ga_modules.core.state_manager import StateManager

logger = logging.getLogger(__name__)


class Coordinator:
    """Routes commands to the right module based on policy."""

    def __init__(self, device_id: str, device_type: str, event_bus, state: StateManager):
        self.device_id = device_id
        self.device_type = device_type  # "gtv", "phone", "tablet", "computer"
        self.bus = event_bus
        self.state = state
        
        # Registered modules
        self.modules: dict[str, Any] = {}
        
        # Optional bridges
        self.ha: Optional[Any] = None  # HA bridge
        self.safety: Optional[Any] = None  # Safety layer
        
        # Routing stats
        self.routes = {"ha_intent": 0, "knowledge": 0, "ha_tool": 0, "local_llm": 0, "cloud_llm": 0}
        
        # Data flywheel
        self.interaction_logger = InteractionLogger()
        self.eval_dataset = EvalDataset(self.interaction_logger)
        self.cost_tracker = CostTracker(self.interaction_logger.db_path)

    def register_module(self, name: str, module: Any):
        """Register a local module."""
        self.modules[name] = module
        logger.info(f"Registered module: {name}")

    def set_ha_bridge(self, ha_bridge: Any):
        """Connect to Home Assistant."""
        self.ha = ha_bridge

    def set_safety_layer(self, safety: Any):
        """Set safety layer."""
        self.safety = safety

    # ============================================================
    # THE ROUTING POLICY
    # ============================================================

    def route_command(self, command: str, context: Optional[dict] = None) -> "Response":
        """
        Decide how to handle a command. Logs every interaction to the data flywheel.
        """
        context = context or self.state.get_context()
        start_time = time.time()
        
        # 1. SAFETY CHECK
        if self.safety and self.safety.is_dangerous(command):
            self.bus.publish("ga.safety.blocked", {
                "device_id": self.device_id,
                "command": command,
                "reason": "Safety rule",
            })
            response = Response("I can't do that for safety reasons.", source="safety")
            self._log_interaction(command, response, context, time.time() - start_time)
            return response

        # 2. HA BUILT-IN INTENTS (200ms fast path)
        if self.ha:
            intent = self.ha.match_intent(command)
            if intent:
                result = self.ha.call_service(intent.service, intent.entity, **intent.params)
                self.routes["ha_intent"] += 1
                response = Response(f"Done. {result}", source="ha_intent")
                self._log_interaction(command, response, context, time.time() - start_time)
                return response

        # 3. GA LOCAL KNOWLEDGE (recipes, calendar, preferences)
        knowledge = self.try_knowledge(command)
        if knowledge:
            self.routes["knowledge"] += 1
            response = Response(knowledge, source="knowledge")
            self._log_interaction(command, response, context, time.time() - start_time)
            return response

        # 4. HA TOOL CALLING (device control via LLM)
        if self.ha and self.ha.can_control(command):
            response = self.via_ha_tool_calling(command, context)
            self.routes["ha_tool"] += 1
            self._log_interaction(command, response, context, time.time() - start_time)
            return response

        # 5. LOCAL LLM (fast, private)
        if "llm" in self.modules:
            response = self.modules["llm"].generate(command, context)
            if response and response.confidence > 0.7:
                self.routes["local_llm"] += 1
                self._log_interaction(command, response, context, time.time() - start_time)
                return Response(
                    response.text,
                    source="local_llm",
                    prompt_tokens=getattr(response, "prompt_tokens", 0),
                    completion_tokens=getattr(response, "completion_tokens", 0),
                    model="local",
                )

        # 6. CLOUD LLM BACKUP (complex queries)
        response = self.via_cloud_llm(command, context)
        self.routes["cloud_llm"] += 1
        self._log_interaction(command, response, context, time.time() - start_time)
        return response
    
    def _log_interaction(self, command: str, response: "Response", context: dict, duration: float):
        """Log an interaction to the data flywheel."""
        try:
            interaction = Interaction(
                command=command,
                model_source=response.source,
                result_text=response.text[:500],
                timestamp=time.time(),
                user=context.get("user", "unknown"),
                room=context.get("room", "unknown"),
                latency_ms=duration * 1000,
                prompt_tokens=getattr(response, "prompt_tokens", 0),
                completion_tokens=getattr(response, "completion_tokens", 0),
                model=getattr(response, "model", ""),
            )
            self.interaction_logger.log(interaction)
        except Exception as e:
            logger.warning(f"Failed to log interaction: {e}")

    def route_voice(self, audio: bytes, context: Optional[dict] = None) -> "Response":
        """Full voice pipeline: transcribe → route → respond."""
        # Transcribe
        if "stt" not in self.modules:
            return Response("No STT module available.", source="error")
        
        text = self.modules["stt"].transcribe(audio)
        if not text:
            return Response("I didn't catch that.", source="error")
        
        return self.route_command(text, context)

    def route_display(self, event: str, data: dict):
        """Route display updates to the right device."""
        if event == "weather.update":
            # Update all displays
            for device_id, display in self.get_display_modules().items():
                display.show_text(data.get("text", ""), "weather")
        elif event == "response.ready":
            # Update the display that made the request
            target = data.get("device_id", self.device_id)
            display = self.get_display_module(target)
            if display:
                display.show_text(data.get("summary", ""), "bottom")

    def try_knowledge(self, command: Optional[str]) -> Optional[str]:
        """Try to answer from local knowledge (recipes, calendar, etc.)."""
        if not command or "knowledge" not in self.modules:
            return None
        return self.modules["knowledge"].answer(command)

    def via_ha_tool_calling(self, command: str, context: Optional[dict] = None) -> "Response":
        """Use HA tool calling for device control."""
        if not self.ha:
            return Response("No HA bridge available.", source="error")
        
        # Let LLM select the right tool
        tools = self.ha.available_tools()
        if "llm" in self.modules:
            tool = self.modules["llm"].select_tool(command, tools, context or {})
            if tool:
                result = self.ha.call_service(tool.name, tool.entity_id, **tool.params)
                return Response(result, source="ha_tool")
        
        return Response("I couldn't figure out which device to control.", source="error")

    def via_cloud_llm(self, command: str, context: Optional[dict] = None) -> "Response":
        """Fall back to cloud LLM."""
        if "llm" in self.modules and hasattr(self.modules["llm"], "generate_cloud"):
            response = self.modules["llm"].generate_cloud(command, context or {})
            if response:
                return Response(
                    response.text,
                    source="cloud_llm",
                    prompt_tokens=getattr(response, "prompt_tokens", 0),
                    completion_tokens=getattr(response, "completion_tokens", 0),
                    model="cloud",
                )
        
        return Response("I'm not sure how to help with that.", source="error")

    def get_display_modules(self) -> dict[str, Any]:
        """Get all display modules."""
        return {name: mod for name, mod in self.modules.items() if name.startswith("display")}

    def get_display_module(self, device_id: str) -> Optional[Any]:
        """Get display module for a device."""
        name = f"display_{device_id}"
        return self.modules.get(name)

    def select_tts_voice(self, user: str) -> str:
        """Select TTS voice per user."""
        voices = {
            "tom": "en_US-libritts-high",
            "andrea": "en_US-amy-medium",
        }
        return voices.get(user, "en_US-libritts-high")

    def get_route_stats(self) -> dict:
        """Get routing statistics."""
        return dict(self.routes)
    
    def get_flywheel_stats(self) -> dict:
        """Get data flywheel statistics."""
        return {
            "interactions": self.interaction_logger.get_stats(),
            "cost": self.cost_tracker.get_cost_summary(),
            "routes": dict(self.routes)
        }


class Response:
    """A response from the coordinator."""

    def __init__(self, text: str, summary: str = None, source: str = "unknown",
                 prompt_tokens: int = 0, completion_tokens: int = 0, model: str = ""):
        self.text = text
        self.summary = summary or text[:100]
        self.source = source
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.model = model
        self.timestamp = time.time()

    def __repr__(self):
        return f"Response({self.source}: {self.text[:50]}...)"
