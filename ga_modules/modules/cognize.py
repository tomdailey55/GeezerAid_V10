"""
GeezerAid — Cognize Module

LLM routing between local llama.cpp and cloud LLM (Nous).
Wraps the multi-backend routing from server_v9.py with a clean interface.

Real path: server_v9.py:1081-1195 (_local_generate, _strix_generate, _mbp_generate)
"""
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """A response from an LLM."""
    text: str
    source: str  # "local" or "cloud"
    confidence: float = 0.5
    prompt_tokens: int = 0
    completion_tokens: int = 0
    
    def __repr__(self):
        return f"LLMResponse({self.source}: {self.text[:50]}...)"


@dataclass
class Tool:
    """A tool (HA service)."""
    name: str
    description: str
    parameters: Optional[dict] = None
    entity_id: Optional[str] = None
    
    def __post_init__(self):
        if self.parameters is None:
            self.parameters = {}


class CognizeModule:
    """LLM routing: local llama.cpp -> cloud LLM backup."""

    def __init__(self, local_url: Optional[str] = None, cloud_url: Optional[str] = None):
        self.local_url = local_url or os.getenv("GA_LOCAL_LLM", "http://localhost:8080")
        self.cloud_url = cloud_url or os.getenv("GA_CLOUD_LLM", "https://inference-api.nousresearch.com/v1")
        self.cloud_key = os.getenv("GA_CLOUD_KEY", "")
        self._local_available = None
        self._last_local_check = 0

    # ============================================================
    # Main interface
    # ============================================================

    def generate(self, prompt: str, context: Optional[dict] = None) -> Optional[LLMResponse]:
        """Generate a response using the best available LLM."""
        if self.local_available:
            result = self._generate_local(prompt, context)
            if result:
                return result
        return self._generate_cloud(prompt, context)

    def generate_cloud(self, prompt: str, context: Optional[dict] = None) -> Optional[LLMResponse]:
        """Force cloud LLM generation."""
        return self._generate_cloud(prompt, context)

    def select_tool(self, command: str, tools: list, context: Optional[dict] = None) -> Optional[Tool]:
        """Select the best tool for a command."""
        if not tools:
            return None
        
        command_lower = command.lower()
        
        # Keyword-based matching
        keywords = {
            "turn_on": ["on", "enable", "activate", "switch on"],
            "turn_off": ["off", "disable", "deactivate", "switch off"],
            "set": ["set", "change", "adjust"],
            "get": ["what", "status", "state", "check"],
            "lock": ["lock", "secure"],
            "unlock": ["unlock", "open"],
        }
        
        for tool in tools:
            tool_action = tool.name.split(".")[-1]
            if tool_action in keywords:
                for kw in keywords[tool_action]:
                    if kw in command_lower:
                        return tool
            # Also check exact tool name
            if tool.name.split(".")[-1].lower() in command_lower:
                return tool
        
        return None

    # ============================================================
    # Local LLM
    # ============================================================

    @property
    def local_available(self) -> bool:
        """Check if local LLM is available (cached for 30s)."""
        now = time.time()
        if self._local_available is None or (now - self._last_local_check) > 30:
            self._local_available = self._check_local()
            self._last_local_check = now
        return self._local_available

    def _check_local(self) -> bool:
        """Check if local LLM is reachable."""
        try:
            import urllib.request
            req = urllib.request.Request(f"{self.local_url}/health", method="GET")
            with urllib.request.urlopen(req, timeout=2) as r:
                return r.status == 200
        except Exception:
            return False

    def _generate_local(self, prompt: str, context: Optional[dict] = None) -> Optional[LLMResponse]:
        """Generate using local llama.cpp."""
        try:
            import urllib.request
            import json
            
            full_prompt = self._build_prompt(prompt, context)
            
            req = urllib.request.Request(
                f"{self.local_url}/v1/chat/completions",
                data=json.dumps({
                    "model": "qwen3.5",
                    "messages": [{"role": "user", "content": full_prompt}],
                    "max_tokens": 1024,
                    "temperature": 0.7,
                }).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read())
                text = data["choices"][0]["message"]["content"]
                usage = data.get("usage") or {}
                return LLMResponse(
                    text=text,
                    source="local",
                    confidence=0.8,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                )
                
        except Exception as e:
            logger.warning(f"Local LLM failed: {e}")
            return None

    # ============================================================
    # Cloud LLM
    # ============================================================

    def _generate_cloud(self, prompt: str, context: Optional[dict] = None) -> Optional[LLMResponse]:
        """Generate using cloud LLM (Nous)."""
        try:
            import urllib.request
            import json
            
            full_prompt = self._build_prompt(prompt, context)
            
            req = urllib.request.Request(
                f"{self.cloud_url}/chat/completions",
                data=json.dumps({
                    "model": "meituan/longcat-2.0:free",
                    "messages": [{"role": "user", "content": full_prompt}],
                    "max_tokens": 1024,
                    "temperature": 0.7,
                }).encode(),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.cloud_key}",
                },
                method="POST",
            )
            
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.loads(r.read())
                text = data["choices"][0]["message"]["content"]
                usage = data.get("usage") or {}
                return LLMResponse(
                    text=text,
                    source="cloud",
                    confidence=0.9,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                )
                
        except Exception as e:
            logger.warning(f"Cloud LLM failed: {e}")
            return None

    # ============================================================
    # Prompt building
    # ============================================================

    def _build_prompt(self, prompt: str, context: Optional[dict] = None) -> str:
        """Build full prompt with context."""
        parts = []
        
        if context:
            if context.get("user"):
                parts.append(f"User: {context['user']}")
            if context.get("room"):
                parts.append(f"Room: {context['room']}")
            if context.get("history"):
                parts.append("History:")
                for turn in context["history"][-5:]:
                    parts.append(f"  {turn['role']}: {turn['text']}")
        
        parts.append(prompt)
        return "\n".join(parts)

    # ============================================================
    # Capabilities
    # ============================================================

    @property
    def capabilities(self) -> list[str]:
        return ["llm", "tool_calling"]

    @property
    def available(self) -> bool:
        return self.local_available or bool(self.cloud_key)
