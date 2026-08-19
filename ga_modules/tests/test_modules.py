"""
Tests for Cognize and Knowledge modules.
"""
import pytest
from unittest.mock import patch, MagicMock
from ga_modules.modules.cognize import CognizeModule, LLMResponse, Tool
from ga_modules.modules.knowledge import KnowledgeModule


class TestCognizeModule:
    def setup_method(self):
        self.cognize = CognizeModule(
            local_url="http://localhost:8080",
            cloud_url="https://cloud.example.com/v1",
        )
        self.cognize.cloud_key = "test_key"

    def test_capabilities(self):
        caps = self.cognize.capabilities
        assert "llm" in caps
        assert "tool_calling" in caps

    def test_available_with_cloud_key(self):
        self.cognize.cloud_key = "key"
        assert self.cognize.available is True

    def test_select_tool_match(self):
        tools = [
            Tool(name="light.turn_on", description="Turn on light"),
            Tool(name="light.turn_off", description="Turn off light"),
        ]
        result = self.cognize.select_tool("turn on the kitchen lights", tools)
        assert result is not None
        assert result.name == "light.turn_on"
    
    def test_select_tool_match_off(self):
        tools = [
            Tool(name="light.turn_on", description="Turn on light"),
            Tool(name="light.turn_off", description="Turn off light"),
        ]
        result = self.cognize.select_tool("turn off the bedroom lights", tools)
        assert result is not None
        assert result.name == "light.turn_off"

    def test_select_tool_no_match(self):
        tools = [Tool(name="light.turn_on", description="Turn on light")]
        result = self.cognize.select_tool("what's the weather", tools)
        assert result is None

    def test_build_prompt_with_context(self):
        context = {"user": "tom", "room": "kitchen", "history": []}
        prompt = self.cognize._build_prompt("hello", context)
        assert "User: tom" in prompt
        assert "Room: kitchen" in prompt
        assert "hello" in prompt


class TestKnowledgeModule:
    def setup_method(self):
        self.knowledge = KnowledgeModule(vault_path="/tmp/fake-vault")

    def test_available_false_when_no_vault(self):
        assert self.knowledge.available is False

    def test_capabilities(self):
        caps = self.knowledge.capabilities
        assert "knowledge" in caps
        assert "recipe_search" in caps

    def test_answer_returns_none_when_empty(self):
        result = self.knowledge.answer("test query")
        assert result is None
