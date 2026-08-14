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
from core.domain.prompt_graph import PromptGraph
from plugins.expert.plugin import ExpertPlugin
from plugins.guidance.plugin import GuidancePlugin
from tests.conftest import MockKnowledgeStorePort, MockLLMPort, make_input

GRAPH = {"nodes": [{"name": "n1"}], "edges": [{"from": "START", "to": "END"}]}


def _rag_graph(*, declares_context: bool = True) -> dict:
    """A graph whose retrieve node runs for real.

    ``event.prompt_graph`` arrives on the wire, so the state schema below is
    the *caller's*. LangGraph drops any key the schema does not declare, which
    is why ``declares_context=False`` must still be validated.

    The answering node is a stub rather than an LLM node: the mock LLM is not
    an LCEL Runnable, and the node under test here is ``retrieve``.
    """
    properties = {"current_question": {"type": "string"},
                  "final_answer": {"type": "string"}}
    if declares_context:
        properties["combined_knowledge_docs"] = {"type": "string"}
    return {
        "nodes": [
            {"name": "retrieve", "input_variables": [], "prompt": ""},
            {"name": "answer", "input_variables": [], "prompt": ""},
        ],
        "edges": [
            {"from": "START", "to": "retrieve"},
            {"from": "retrieve", "to": "answer"},
            {"from": "answer", "to": "END"},
        ],
        "state": {"type": "object", "properties": properties},
    }


def _no_retrieve_graph() -> dict:
    """A valid graph that never retrieves — makes no claim about context."""
    return {
        "nodes": [{"name": "answer", "input_variables": [], "prompt": ""}],
        "edges": [{"from": "START", "to": "answer"}, {"from": "answer", "to": "END"}],
        "state": {"type": "object", "properties": {
            "current_question": {"type": "string"},
            "final_answer": {"type": "string"},
        }},
    }


async def _answer_node(state) -> dict:
    """Stands in for the LLM node — asserts the fabrication."""
    return {"final_answer": FABRICATION}

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
    """The path with no sources — a sources-keyed check would flag them all.

    These drive the REAL graph. Mocking ``PromptGraph`` wholesale skips the
    retrieve node, which is exactly the code deciding whether validation runs.
    """

    async def _run(
        self, plugin: ExpertPlugin, *, graph: dict | None = None, **kw,
    ) -> None:
        """Drives the real graph, stubbing only the answering node."""
        real_from_definition = PromptGraph.from_definition

        def _with_answer_stub(definition: dict):
            g = real_from_definition(definition)
            real_compile = g.compile

            def compile_with_stub(llm, special_nodes=None):
                nodes = dict(special_nodes or {})
                nodes.setdefault("answer", _answer_node)
                return real_compile(llm=llm, special_nodes=nodes)

            g.compile = compile_with_stub  # type: ignore[method-assign]
            return g

        with patch.object(
            PromptGraph, "from_definition", staticmethod(_with_answer_stub),
        ):
            await plugin.handle(
                make_input(
                    message="who founded this?",
                    promptGraph=graph or _rag_graph(**kw),
                )
            )

    def _plugin(self, store: MockKnowledgeStorePort, **kw) -> ExpertPlugin:
        return ExpertPlugin(
            llm=MockLLMPort(response=FABRICATION), knowledge_store=store, **kw,
        )

    async def test_graph_path_flags_on_empty_knowledge(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        plugin = self._plugin(
            _EmptyStore(), faithfulness_validator=ContextSufficiencyValidator(),
        )
        with caplog.at_level(logging.WARNING, logger="plugins.expert.plugin"):
            await self._run(plugin)
        assert _flagged(caplog)

    async def test_graph_path_does_not_flag_when_knowledge_exists(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Sources are empty here by design — only the context may decide."""
        plugin = self._plugin(
            MockKnowledgeStorePort(),
            score_threshold=0.0,
            faithfulness_validator=ContextSufficiencyValidator(),
        )
        with caplog.at_level(logging.WARNING, logger="plugins.expert.plugin"):
            await self._run(plugin)
        assert not _flagged(caplog)

    async def test_validation_survives_a_state_schema_that_drops_the_key(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The graph definition is caller-supplied.

        Reading ``combined_knowledge_docs`` back from the final state made this
        feature silently inert for any RAG graph whose schema simply did not
        list it — a real zero-context answer became indistinguishable from a
        graph that never retrieved at all.
        """
        plugin = self._plugin(
            _EmptyStore(), faithfulness_validator=ContextSufficiencyValidator(),
        )
        with caplog.at_level(logging.WARNING, logger="plugins.expert.plugin"):
            await self._run(plugin, declares_context=False)
        assert _flagged(caplog), (
            "retrieval ran and found nothing, but validation was skipped "
            "because the caller's schema dropped the key"
        )

    async def test_a_graph_that_never_retrieves_is_not_validated(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The other half of the distinction. A graph with no retrieve node
        makes no claim about context; flagging it would condemn every answer
        from every non-RAG graph."""
        plugin = self._plugin(
            _EmptyStore(), faithfulness_validator=ContextSufficiencyValidator(),
        )
        with caplog.at_level(logging.WARNING, logger="plugins.expert.plugin"):
            await self._run(plugin, graph=_no_retrieve_graph())
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
