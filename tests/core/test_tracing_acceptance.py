"""In-process acceptance checks for the trace hierarchy (US1, US4).

These are the persisted acceptance specs for workspace#039-vc-rag-observability:
each test maps to a spec.md acceptance scenario and asserts the span-schema v1
contract through the real wiring with an InMemorySpanExporter.
"""

from itertools import cycle

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from core.adapters.langchain_llm import LangChainLLMAdapter
from core.config import BaseConfig
from core.tracing import handle_span, shutdown_tracing
from core.tracing_callbacks import VCTracingCallbackHandler
from plugins.expert.plugin import ExpertPlugin
from plugins.guidance.plugin import GuidancePlugin
from tests.conftest import MockKnowledgeStorePort, MockLLMPort, make_input

GRAPH_DEFINITION = {
    "nodes": [
        {"name": "retrieve", "input_variables": [], "prompt": "unused — special node", "output": {}},
        {
            "name": "answer_question",
            "input_variables": ["current_question", "combined_knowledge_docs"],
            "prompt": "Answer {current_question} using {combined_knowledge_docs}",
            "output": {},
        },
    ],
    "edges": [
        {"from": "START", "to": "retrieve"},
        {"from": "retrieve", "to": "answer_question"},
        {"from": "answer_question", "to": "END"},
    ],
    "state": {
        "type": "object",
        "properties": {
            "messages": {"type": "array", "items": {"type": "object"}},
            "current_question": {"type": "string"},
            "conversation": {"type": "string"},
            "bok_id": {"type": "string"},
            "description": {"type": "string"},
            "display_name": {"type": "string"},
            "combined_knowledge_docs": {"type": "string"},
            "answer_question": {"type": "string"},
            "final_answer": {"type": "string"},
        },
    },
}


def _tracing_config():
    return BaseConfig(
        llm_base_url="http://local-model",
        tracing_enabled=True,
        tracing_otlp_endpoint="http://collector.internal/v1/traces",
        tracing_content_max_chars=100,
    )


def _fake_chat_model(**message_kwargs) -> GenericFakeChatModel:
    """An endless fake BaseChatModel whose calls fire real LangChain callbacks."""
    message = AIMessage(content="fake answer", **message_kwargs)
    model = GenericFakeChatModel(messages=cycle([message]))
    model.callbacks = [VCTracingCallbackHandler(_tracing_config())]
    return model


async def test_guidance_trace_has_root_and_retrieval_children(traced_exporter) -> None:
    event = make_input()
    with handle_span(_tracing_config(), event, "guidance"):
        await GuidancePlugin(MockLLMPort(), MockKnowledgeStorePort()).handle(event)
    shutdown_tracing()
    spans = traced_exporter.get_finished_spans()
    assert {span.name for span in spans} >= {"vc.handle", "vc.retrieval"}


async def test_us1_as1_guidance_full_tree(traced_exporter) -> None:
    """US1-AS1: root → query_processing stage + per-collection retrieval, all timed."""
    event = make_input(history=[{"content": "Hi", "role": "human"}, {"content": "Hello!", "role": "assistant"}])
    with handle_span(_tracing_config(), event, "guidance"):
        await GuidancePlugin(MockLLMPort(), MockKnowledgeStorePort()).handle(event)
    shutdown_tracing()
    spans = traced_exporter.get_finished_spans()
    by_name: dict[str, list] = {}
    for span in spans:
        by_name.setdefault(span.name, []).append(span)
    root = by_name["vc.handle"][0]
    assert root.attributes["vc.plugin"] == "guidance"
    assert root.attributes["vc.engine"]
    assert len(by_name["vc.stage query_processing"]) == 1
    assert by_name["vc.stage query_processing"][0].attributes["vc.history_turns"] == 2
    assert len(by_name["vc.retrieval"]) == 3  # one per guidance collection
    root_ctx = root.context
    for span in spans:
        assert span.end_time is not None and span.end_time > span.start_time
        if span.name != "vc.handle":
            assert span.context.trace_id == root_ctx.trace_id


async def test_us1_as2_expert_graph_nodes(traced_exporter) -> None:
    """US1-AS2: expert prompt-graph query → retrieval + one chat span per LLM graph node."""
    adapter = LangChainLLMAdapter(_fake_chat_model())
    event = make_input(bodyOfKnowledgeID="bok-1", promptGraph=GRAPH_DEFINITION)
    with handle_span(_tracing_config(), event, "expert"):
        await ExpertPlugin(llm=adapter, knowledge_store=MockKnowledgeStorePort()).handle(event)
    shutdown_tracing()
    spans = traced_exporter.get_finished_spans()
    names = [span.name for span in spans]
    assert "vc.retrieval" in names
    chat_spans = [span for span in spans if span.name.startswith("chat ")]
    assert len(chat_spans) == 1  # one LLM graph node in the definition
    assert chat_spans[0].attributes["gen_ai.operation.name"] == "chat"


async def test_us1_as3_durations(traced_exporter) -> None:
    """US1-AS3: root duration spans the whole handle window — P50/P95 raw material."""
    event = make_input()
    with handle_span(_tracing_config(), event, "guidance"):
        await GuidancePlugin(MockLLMPort(), MockKnowledgeStorePort()).handle(event)
    shutdown_tracing()
    spans = traced_exporter.get_finished_spans()
    root = next(span for span in spans if span.name == "vc.handle")
    children = [span for span in spans if span.name != "vc.handle"]
    assert children
    for child in children:
        assert child.start_time >= root.start_time
        assert child.end_time <= root.end_time
    durations = [(span.end_time - span.start_time) for span in spans]
    assert all(duration > 0 for duration in durations)


async def test_streaming_single_span(traced_exporter) -> None:
    """Edge case (A-7): a consumed stream() yields exactly one chat span, ended at stream end."""
    adapter = LangChainLLMAdapter(_fake_chat_model())
    chunks = [chunk async for chunk in adapter.stream([{"role": "human", "content": "hi"}])]
    assert chunks
    shutdown_tracing()
    chat_spans = [span for span in traced_exporter.get_finished_spans() if span.name.startswith("chat ")]
    assert len(chat_spans) == 1
    assert chat_spans[0].end_time is not None


async def test_us4_as1_two_calls_have_tokens(traced_exporter) -> None:
    """US4-AS1: condensation + generation → two chat spans, each with token usage."""
    model = _fake_chat_model(usage_metadata={"input_tokens": 7, "output_tokens": 11, "total_tokens": 18})
    adapter = LangChainLLMAdapter(model)
    event = make_input(history=[{"content": "Hi", "role": "human"}])
    with handle_span(_tracing_config(), event, "guidance"):
        await GuidancePlugin(adapter, MockKnowledgeStorePort()).handle(event)
    shutdown_tracing()
    chat_spans = [span for span in traced_exporter.get_finished_spans() if span.name.startswith("chat ")]
    assert len(chat_spans) == 2  # condense + generate
    for span in chat_spans:
        assert span.attributes["gen_ai.usage.input_tokens"] == 7
        assert span.attributes["gen_ai.usage.output_tokens"] == 11
        assert span.end_time > span.start_time


async def test_us4_as2_graph_path_tokens(traced_exporter) -> None:
    """US4-AS2 (risk R-7): graph nodes bypass the adapter, yet chat spans carry tokens."""
    model = _fake_chat_model(usage_metadata={"input_tokens": 13, "output_tokens": 29, "total_tokens": 42})
    adapter = LangChainLLMAdapter(model)
    event = make_input(bodyOfKnowledgeID="bok-1", promptGraph=GRAPH_DEFINITION)
    with handle_span(_tracing_config(), event, "expert"):
        await ExpertPlugin(llm=adapter, knowledge_store=MockKnowledgeStorePort()).handle(event)
    shutdown_tracing()
    chat_spans = [span for span in traced_exporter.get_finished_spans() if span.name.startswith("chat ")]
    assert len(chat_spans) == 1
    assert chat_spans[0].attributes["gen_ai.usage.input_tokens"] == 13
    assert chat_spans[0].attributes["gen_ai.usage.output_tokens"] == 29


async def test_us4_as3_absent_usage_means_absent_attributes(traced_exporter) -> None:
    """US4-AS3: provider without usage_metadata → token attributes absent, never zero."""
    adapter = LangChainLLMAdapter(_fake_chat_model())  # no usage_metadata
    event = make_input()
    with handle_span(_tracing_config(), event, "generic"):
        await adapter.invoke([{"role": "human", "content": event.message}])
    shutdown_tracing()
    chat_spans = [span for span in traced_exporter.get_finished_spans() if span.name.startswith("chat ")]
    assert len(chat_spans) == 1
    assert "gen_ai.usage.input_tokens" not in chat_spans[0].attributes
    assert "gen_ai.usage.output_tokens" not in chat_spans[0].attributes
