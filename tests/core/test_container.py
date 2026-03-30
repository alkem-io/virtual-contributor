"""Unit tests for IoC Container."""

from __future__ import annotations

import pytest

from core.container import Container, ContainerError
from core.ports.llm import LLMPort
from core.ports.knowledge_store import KnowledgeStorePort
from tests.conftest import MockLLMPort, MockKnowledgeStorePort


class TestContainer:
    def test_register_and_resolve(self):
        container = Container()
        mock = MockLLMPort()
        container.register(LLMPort, mock)
        assert container.resolve(LLMPort) is mock

    def test_resolve_missing_port_raises(self):
        container = Container()
        with pytest.raises(ContainerError, match="No adapter registered"):
            container.resolve(LLMPort)

    def test_resolve_for_plugin_basic(self):
        container = Container()
        mock_llm = MockLLMPort()
        container.register(LLMPort, mock_llm)

        class FakePlugin:
            name = "fake"

            def __init__(self, llm: LLMPort):
                self.llm = llm

        resolved = container.resolve_for_plugin(FakePlugin)
        assert resolved["llm"] is mock_llm

    def test_resolve_for_plugin_multiple_ports(self):
        container = Container()
        mock_llm = MockLLMPort()
        mock_ks = MockKnowledgeStorePort()
        container.register(LLMPort, mock_llm)
        container.register(KnowledgeStorePort, mock_ks)

        class MultiPlugin:
            name = "multi"

            def __init__(self, llm: LLMPort, knowledge_store: KnowledgeStorePort):
                self.llm = llm
                self.knowledge_store = knowledge_store

        resolved = container.resolve_for_plugin(MultiPlugin)
        assert resolved["llm"] is mock_llm
        assert resolved["knowledge_store"] is mock_ks

    def test_resolve_for_plugin_missing_port(self):
        container = Container()

        class NeedsLLM:
            name = "needs-llm"

            def __init__(self, llm: LLMPort):
                self.llm = llm

        with pytest.raises(ContainerError, match="requires port"):
            container.resolve_for_plugin(NeedsLLM)

    def test_overwrite_registration(self):
        container = Container()
        mock1 = MockLLMPort(response="first")
        mock2 = MockLLMPort(response="second")
        container.register(LLMPort, mock1)
        container.register(LLMPort, mock2)
        assert container.resolve(LLMPort) is mock2
