"""Evaluation remains independent of runtime tracing."""

import ast
from pathlib import Path

from core.config import BaseConfig
from core.container import Container
from core.ports.knowledge_store import QueryResult
from core.ports.knowledge_store import KnowledgeStorePort
from core.ports.llm import LLMPort
from evaluation.pipeline_invoker import PipelineInvoker
from evaluation.tracing import TracingKnowledgeStore


def test_evaluation_does_not_import_runtime_tracing() -> None:
    for source in Path("evaluation").glob("*.py"):
        tree = ast.parse(source.read_text())
        assert not any(
            isinstance(node, ast.ImportFrom) and node.module == "core.tracing"
            for node in ast.walk(tree)
        )


async def test_invoker_setup_retains_evaluation_context_capture(monkeypatch) -> None:
    class Store:
        def __init__(self, **kwargs) -> None:
            pass

        async def query(self, collection, query_texts, n_results=10, where=None):
            return QueryResult([["captured"]], [[{}]], [[0.1]], [["id"]])

    class Plugin:
        async def startup(self) -> None:
            pass

    monkeypatch.setattr("core.adapters.chromadb.ChromaDBAdapter", Store)
    monkeypatch.setattr("evaluation.pipeline_invoker.create_llm_adapter", lambda config: object())
    monkeypatch.setattr(
        "evaluation.pipeline_invoker.PluginRegistry.discover", lambda self, name: Plugin
    )
    invoker = PipelineInvoker("generic", BaseConfig(llm_base_url="http://local"))
    await invoker.setup()
    assert isinstance(invoker._tracing_store, TracingKnowledgeStore)
    await invoker._tracing_store.query("knowledge", ["question"])
    assert invoker._tracing_store.get_retrieved_contexts() == ["captured"]


async def test_invoker_wires_hierarchy_settings_to_expert(monkeypatch) -> None:
    captured: dict = {}

    class Store:
        def __init__(self, **kwargs) -> None:
            pass

    class Plugin:
        def __init__(self, *, hierarchical_retrieval_enabled=False, hierarchy_max_branches=0) -> None:
            captured.update(
                enabled=hierarchical_retrieval_enabled, branches=hierarchy_max_branches,
            )

        async def startup(self) -> None:
            pass

    monkeypatch.setattr("core.adapters.chromadb.ChromaDBAdapter", Store)
    monkeypatch.setattr("evaluation.pipeline_invoker.create_llm_adapter", lambda config: object())
    monkeypatch.setattr("evaluation.pipeline_invoker.PluginRegistry.discover", lambda self, name: Plugin)
    invoker = PipelineInvoker(
        "expert", BaseConfig(
            llm_base_url="http://local", expert_hierarchical_retrieval_enabled=True,
            expert_hierarchy_max_branches=2,
        ),
    )
    await invoker.setup()
    assert captured == {"enabled": True, "branches": 2}


async def test_invoker_nondefault_production_composition_and_fingerprint(monkeypatch) -> None:
    """Evaluation must retain production retrieval/answering construction."""
    captured: dict = {}

    class Store:
        async def query(self, *args, **kwargs):
            return QueryResult([[]], [[]], [[]], [[]])

        async def query_lexical(self, *args, **kwargs):
            return QueryResult([[]], [[]], [[]], [[]])

    class Plugin:
        def __init__(
            self, llm: LLMPort, knowledge_store: KnowledgeStorePort, *, n_results=0,
            score_threshold=0.0, max_context_chars=0, answering_temperature=None,
            hierarchical_retrieval_enabled=False, hierarchy_max_branches=0,
            hybrid_config=None, rerank_candidate_n=0, rerank_top_k=0,
            context_observer=None,
        ) -> None:
            captured.update(locals())

        async def startup(self) -> None:
            pass

    def compose(config: BaseConfig, container: Container) -> None:
        container.register(LLMPort, object())
        container.register(KnowledgeStorePort, Store())

    monkeypatch.setattr("main._create_adapters", compose)
    monkeypatch.setattr("evaluation.pipeline_invoker.PluginRegistry.discover", lambda *_: Plugin)
    config = BaseConfig(
        plugin_type="expert", llm_base_url="http://local", expert_n_results=9,
        expert_min_score=0.1, max_context_chars=1200,
        expert_hierarchical_retrieval_enabled=True, expert_hierarchy_max_branches=2,
        hybrid_retrieval_enabled=True, rerank_enabled=True, rerank_candidate_n=11,
        rerank_top_k=4, routing_enabled=True, query_rewrite_gating_enabled=True,
        routing_complex_context_chars=12_000,
        answering_llm_temperature=0.2, vector_db_distance_fn="l2",
        embeddings_model_name="sentinel-embedding",
    )
    invoker = PipelineInvoker("expert", config)
    await invoker.setup()
    assert captured["n_results"] == 9 and captured["score_threshold"] == 0.1
    assert captured["max_context_chars"] == 1200
    assert captured["answering_temperature"] == 0.2
    assert captured["hybrid_config"] is config
    assert captured["rerank_candidate_n"] == 11 and captured["rerank_top_k"] == 4
    assert captured["hierarchical_retrieval_enabled"] is True
    assert isinstance(captured["knowledge_store"], TracingKnowledgeStore)
    fingerprint = invoker.composition_fingerprint
    assert len(fingerprint) == 64 and fingerprint == invoker.composition_fingerprint
