"""Faithfulness wiring across all three generation paths.

Expert generates in two places and guidance in one. The graph path is the one
most easily missed: the existing suite mocks PromptGraph wholesale, and the
path returns no sources at all — which is exactly why the check keys off the
context string rather than `Response.sources`.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.domain.faithfulness import ContextSufficiencyValidator
from core.ports.faithfulness import FaithfulnessVerdict
from core.ports.knowledge_store import QueryResult
from plugins.expert.plugin import ExpertPlugin
from plugins.guidance.plugin import GuidancePlugin
from tests.conftest import MockKnowledgeStorePort, MockLLMPort, make_input

GRAPH = {"nodes": [{"name": "n1"}], "edges": [{"from": "START", "to": "END"}]}

FABRICATION = "The space was founded in 1997 by Dr. Amelia Hartwell."


class _EmptyStore(MockKnowledgeStorePort):
    """Retrieval finds nothing — the case this feature exists for."""

    async def query(
        self, collection: str, query_texts: list[str], n_results: int = 10,
    ) -> QueryResult:
        self.query_calls.append((collection, query_texts, n_results))
        return QueryResult(documents=[[]], metadatas=[[]], distances=[[]], ids=[[]])


class _Raises:
    def validate(self, *, answer: str, context: str) -> FaithfulnessVerdict:
        raise RuntimeError("validator exploded")


def _flagged(caplog: pytest.LogCaptureFixture) -> bool:
    return any("Unsupported answer" in r.getMessage() for r in caplog.records)


class TestExpertSimplePath:
    async def test_fabrication_on_empty_context_is_flagged(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        plugin = ExpertPlugin(
            llm=MockLLMPort(response=FABRICATION),
            knowledge_store=_EmptyStore(),
            faithfulness_validator=ContextSufficiencyValidator(),
        )
        with caplog.at_level(logging.WARNING, logger="plugins.expert.plugin"):
            await plugin.handle(make_input(message="who founded this space?"))
        assert _flagged(caplog)

    async def test_a_hedged_answer_is_not_flagged(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Declining without evidence is the model behaving correctly."""
        plugin = ExpertPlugin(
            llm=MockLLMPort(response="I don't have enough information to answer."),
            knowledge_store=_EmptyStore(),
            faithfulness_validator=ContextSufficiencyValidator(),
        )
        with caplog.at_level(logging.WARNING, logger="plugins.expert.plugin"):
            await plugin.handle(make_input(message="who founded this space?"))
        assert not _flagged(caplog)

    async def test_a_real_answer_with_context_is_not_flagged(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        plugin = ExpertPlugin(
            llm=MockLLMPort(response="A paraphrase sharing no words."),
            knowledge_store=MockKnowledgeStorePort(),   # returns real docs
            score_threshold=0.0,
            faithfulness_validator=ContextSufficiencyValidator(),
        )
        with caplog.at_level(logging.WARNING, logger="plugins.expert.plugin"):
            await plugin.handle(make_input(message="what is the mission?"))
        assert not _flagged(caplog)


class TestExpertGraphPath:
    """The path with no sources — a sources-keyed check would flag them all."""

    async def _run(self, plugin: ExpertPlugin, knowledge: str) -> None:
        mock_graph = MagicMock()
        mock_graph.compile = MagicMock(return_value=mock_graph)
        mock_graph.invoke = AsyncMock(return_value={
            "final_answer": FABRICATION,
            "combined_knowledge_docs": knowledge,
        })
        with patch("core.domain.prompt_graph.PromptGraph") as MockPromptGraph:
            MockPromptGraph.from_definition.return_value = mock_graph
            await plugin.handle(make_input(message="who founded this?", promptGraph=GRAPH))

    async def test_graph_path_flags_on_empty_knowledge(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        plugin = ExpertPlugin(
            llm=MockLLMPort(response="ignored"),
            knowledge_store=_EmptyStore(),
            faithfulness_validator=ContextSufficiencyValidator(),
        )
        with caplog.at_level(logging.WARNING, logger="plugins.expert.plugin"):
            await self._run(plugin, knowledge="")
        assert _flagged(caplog)

    async def test_graph_path_does_not_flag_when_knowledge_exists(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Sources are empty here by design — only the context may decide."""
        plugin = ExpertPlugin(
            llm=MockLLMPort(response="ignored"),
            knowledge_store=_EmptyStore(),
            faithfulness_validator=ContextSufficiencyValidator(),
        )
        with caplog.at_level(logging.WARNING, logger="plugins.expert.plugin"):
            await self._run(plugin, knowledge="[source:0] real retrieved content")
        assert not _flagged(caplog)


class TestGuidancePath:
    async def test_the_sentinel_context_is_flagged(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Guidance says "No relevant context found." instead of an empty string."""
        plugin = GuidancePlugin(
            llm=MockLLMPort(response=FABRICATION),
            knowledge_store=_EmptyStore(),
            faithfulness_validator=ContextSufficiencyValidator(),
        )
        with caplog.at_level(logging.WARNING, logger="plugins.guidance.plugin"):
            await plugin.handle(make_input(message="who founded this space?"))
        assert _flagged(caplog)

    async def test_real_context_is_not_flagged(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        plugin = GuidancePlugin(
            llm=MockLLMPort(response=FABRICATION),
            knowledge_store=MockKnowledgeStorePort(),
            score_threshold=0.0,
            faithfulness_validator=ContextSufficiencyValidator(),
        )
        with caplog.at_level(logging.WARNING, logger="plugins.guidance.plugin"):
            await plugin.handle(make_input(message="what is the mission?"))
        assert not _flagged(caplog)


class TestDisabledDoesNothing:
    async def test_expert_simple_path_disabled_never_flags(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        plugin = ExpertPlugin(
            llm=MockLLMPort(response=FABRICATION), knowledge_store=_EmptyStore(),
        )
        with caplog.at_level(logging.WARNING, logger="plugins.expert.plugin"):
            await plugin.handle(make_input(message="who founded this?"))
        assert not _flagged(caplog)

    async def test_expert_graph_path_disabled_never_flags(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        plugin = ExpertPlugin(
            llm=MockLLMPort(response="ignored"), knowledge_store=_EmptyStore(),
        )
        mock_graph = MagicMock()
        mock_graph.compile = MagicMock(return_value=mock_graph)
        mock_graph.invoke = AsyncMock(return_value={
            "final_answer": FABRICATION, "combined_knowledge_docs": "",
        })
        with caplog.at_level(logging.WARNING, logger="plugins.expert.plugin"):
            with patch("core.domain.prompt_graph.PromptGraph") as MockPromptGraph:
                MockPromptGraph.from_definition.return_value = mock_graph
                await plugin.handle(
                    make_input(message="who founded this?", promptGraph=GRAPH),
                )
        assert not _flagged(caplog)

    async def test_guidance_disabled_never_flags(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        plugin = GuidancePlugin(
            llm=MockLLMPort(response=FABRICATION), knowledge_store=_EmptyStore(),
        )
        with caplog.at_level(logging.WARNING, logger="plugins.guidance.plugin"):
            await plugin.handle(make_input(message="who founded this?"))
        assert not _flagged(caplog)


class TestTheAnswerIsNeverAffected:
    async def test_a_flagged_answer_reaches_the_member_unchanged(self) -> None:
        """This only observes. It must not alter, delay, or withhold."""
        off = await ExpertPlugin(
            llm=MockLLMPort(response=FABRICATION), knowledge_store=_EmptyStore(),
        ).handle(make_input(message="who founded this?"))
        on = await ExpertPlugin(
            llm=MockLLMPort(response=FABRICATION), knowledge_store=_EmptyStore(),
            faithfulness_validator=ContextSufficiencyValidator(),
        ).handle(make_input(message="who founded this?"))
        assert on.result == off.result
        assert len(on.sources) == len(off.sources)

    async def test_a_raising_validator_never_costs_the_answer(self) -> None:
        response = await ExpertPlugin(
            llm=MockLLMPort(response=FABRICATION), knowledge_store=_EmptyStore(),
            faithfulness_validator=_Raises(),
        ).handle(make_input(message="who founded this?"))
        assert response.result == FABRICATION


class TestLogsCarryNoMemberContent:
    async def test_neither_answer_nor_context_is_logged(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        secret = "MEMBER-PRIVATE-SENTENCE-42"
        plugin = ExpertPlugin(
            llm=MockLLMPort(response=f"{FABRICATION} {secret}"),
            knowledge_store=_EmptyStore(),
            faithfulness_validator=ContextSufficiencyValidator(),
        )
        with caplog.at_level(logging.DEBUG):
            await plugin.handle(make_input(message="who founded this?"))
        assert _flagged(caplog)
        assert not any(secret in r.getMessage() for r in caplog.records)
