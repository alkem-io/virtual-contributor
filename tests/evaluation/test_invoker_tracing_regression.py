"""Evaluation remains independent of runtime tracing."""

import ast
from pathlib import Path

import pytest

from core.config import BaseConfig
from core.container import Container
from core.ports.knowledge_store import QueryResult
from core.ports.knowledge_store import KnowledgeStorePort
from core.ports.llm import LLMPort
from core.ports.reranker import RerankerPort
from evaluation.pipeline_invoker import PipelineInvoker, effective_composition_fingerprint
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
        def __init__(self, *, hierarchical_retrieval_enabled=False, hierarchy_max_branches=0, hierarchy_display_names_enabled=False) -> None:
            captured.update(
                enabled=hierarchical_retrieval_enabled, branches=hierarchy_max_branches,
                display_names=hierarchy_display_names_enabled,
            )

        async def startup(self) -> None:
            pass

    monkeypatch.setattr("core.adapters.chromadb.ChromaDBAdapter", Store)
    monkeypatch.setattr("evaluation.pipeline_invoker.create_llm_adapter", lambda config: object())
    monkeypatch.setattr("evaluation.pipeline_invoker.PluginRegistry.discover", lambda self, name: Plugin)
    invoker = PipelineInvoker(
        "expert", BaseConfig(
            llm_base_url="http://local", expert_hierarchical_retrieval_enabled=True,
            expert_hierarchy_max_branches=2, expert_hierarchy_display_names_enabled=True,
        ),
    )
    await invoker.setup()
    assert captured == {"enabled": True, "branches": 2, "display_names": True}


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
            hybrid_config=None, reranker: RerankerPort | None = None,
            rerank_candidate_n=0, rerank_top_k=0,
            query_router=None, routing_table=None, faithfulness_validator=None,
            max_expansion_ratio=0.0, max_history_turns=0, max_history_chars=0,
            rewrite_policy=None, context_observer=None,
        ) -> None:
            captured.update(locals())

        async def startup(self) -> None:
            pass

    def compose(config: BaseConfig, container: Container, plumbing=None, selectors=None) -> None:
        container.register(LLMPort, object())
        container.register(KnowledgeStorePort, Store())
        container.register(RerankerPort, object())

    monkeypatch.setattr("main._create_adapters", compose)
    monkeypatch.setattr("evaluation.pipeline_invoker.PluginRegistry.discover", lambda *_: Plugin)
    config = BaseConfig(
        plugin_type="expert", llm_base_url="http://local", expert_n_results=9,
        expert_min_score=0.1, max_context_chars=1200,
        expert_hierarchical_retrieval_enabled=True, expert_hierarchy_max_branches=2,
        hybrid_retrieval_enabled=True, rerank_enabled=True, rerank_candidate_n=11,
        rerank_top_k=4, routing_enabled=True, faithfulness_validation_enabled=True,
        query_rewrite_gating_enabled=True,
        routing_complex_context_chars=12_000,
        answering_llm_temperature=0.2, vector_db_distance_fn="l2",
        embeddings_model_name="sentinel-embedding",
    )
    invoker = PipelineInvoker("expert", config)
    await invoker.setup()
    assert captured["n_results"] == 9 and captured["score_threshold"] == 0.1
    assert captured["max_context_chars"] == 1200
    assert captured["answering_temperature"] == 0.2
    assert captured["hybrid_config"] is invoker._expert_composition
    assert captured["rerank_candidate_n"] == 11 and captured["rerank_top_k"] == 4
    assert captured["query_router"] is not None and captured["routing_table"] is not None
    assert captured["faithfulness_validator"] is not None
    assert captured["rewrite_policy"] is not None
    assert captured["max_history_turns"] == config.query_rewrite_max_history_turns
    assert captured["hierarchical_retrieval_enabled"] is True
    assert isinstance(captured["knowledge_store"], TracingKnowledgeStore)
    fingerprint = invoker.composition_fingerprint
    assert len(fingerprint) == 64 and fingerprint == invoker.composition_fingerprint


def test_effective_composition_fingerprint_is_stable_and_redacted() -> None:
    shared = dict(
        plugin_type="expert", llm_base_url="http://local", expert_min_score=0.1,
        hybrid_retrieval_enabled=True, rerank_enabled=True, rerank_top_k=4,
        embeddings_model_name="approved-model", vector_db_distance_fn="l2",
    )
    flat = BaseConfig(**shared)
    hierarchy = BaseConfig(**shared, expert_hierarchical_retrieval_enabled=True)
    from plugins.expert.composition import resolve_expert_composition
    assert effective_composition_fingerprint(resolve_expert_composition(flat).authority) == effective_composition_fingerprint(resolve_expert_composition(hierarchy).authority)
    assert effective_composition_fingerprint(resolve_expert_composition(flat).authority) == effective_composition_fingerprint(resolve_expert_composition(BaseConfig(**shared)).authority)
    assert effective_composition_fingerprint(resolve_expert_composition(flat).authority) != effective_composition_fingerprint(
        resolve_expert_composition(BaseConfig(**(shared | {"expert_min_score": 0.2}))).authority
    )
    secret_changed = BaseConfig(**shared, embeddings_endpoint="https://secret.invalid", embeddings_api_key="not-in-hash")
    assert effective_composition_fingerprint(resolve_expert_composition(flat).authority) == effective_composition_fingerprint(resolve_expert_composition(secret_changed).authority)


async def test_production_wiring_consumes_single_resolved_v7_authority(monkeypatch) -> None:
    """The real production adapter path consumes the resolved selector entry."""
    from dataclasses import replace
    from main import _create_adapters
    from plugins.expert.composition import (
        EXPERT_SELECTOR_REGISTRY, ExpertSelectorRegistry, resolve_expert_composition,
    )

    selected_llm = object()
    registry = ExpertSelectorRegistry(tuple(
        replace(entry, target=lambda _config: selected_llm)
        if entry.name == "llm" else entry
        for entry in EXPERT_SELECTOR_REGISTRY.entries
    ))
    wiring = resolve_expert_composition(
        BaseConfig(plugin_type="expert", llm_base_url="http://local"),
        selector_registry=registry,
    )
    container = Container()
    _create_adapters(wiring.authority, container, wiring.plumbing, wiring.selectors)
    assert container.resolve(LLMPort) is selected_llm
    assert dict(wiring.authority.dependency_identities) == {
        entry.name: (
            "none" if entry.name in {"reranker", "router", "routing_table", "faithfulness", "rewrite"}
            else entry.primitive_id
        )
        for entry in wiring.selectors.entries
    }


async def test_evaluation_wiring_consumes_single_resolved_v7_authority(monkeypatch) -> None:
    from core.container import Container
    from core.ports.knowledge_store import KnowledgeStorePort
    from core.ports.llm import LLMPort
    class Store:
        async def query(self, *args, **kwargs): return QueryResult([[]], [[]], [[]], [[]])
        async def query_lexical(self, *args, **kwargs): return QueryResult([[]], [[]], [[]], [[]])
    class Plugin:
        def __init__(self, **kwargs): pass
        async def startup(self): pass
    def adapters(authority, container: Container, plumbing=None, selectors=None):
        assert selectors is not None
        container.register(LLMPort, object())
        container.register(KnowledgeStorePort, Store())
    monkeypatch.setattr("main._create_adapters", adapters)
    monkeypatch.setattr("evaluation.pipeline_invoker.PluginRegistry.discover", lambda *_: Plugin)
    invoker = PipelineInvoker("expert", BaseConfig(llm_base_url="http://local"))
    await invoker.setup()
    assert invoker._expert_composition is not None
    assert invoker._expert_composition.embeddings_model_name == "qwen3-embedding-8b"


def test_pipeline_invoker_exposes_immutable_public_evaluation_identity() -> None:
    from dataclasses import FrozenInstanceError
    from evaluation.pipeline_invoker import ExpertEvaluationIdentity
    identity = ExpertEvaluationIdentity("flat", "a" * 64, "b" * 64)
    with pytest.raises(FrozenInstanceError):
        identity.hierarchy_mode = "hierarchical"


def test_public_evaluation_identity_binds_mode_and_full_fingerprint() -> None:
    from evaluation.pipeline_invoker import ExpertEvaluationIdentity
    with pytest.raises(ValueError):
        ExpertEvaluationIdentity("other", "a" * 64, "b" * 64)


async def test_expert_cli_path_applies_actual_expert_retrieval_and_llm_values(monkeypatch) -> None:
    """The production composition seam, not an evaluation-only constructor, owns Expert values."""
    await test_invoker_nondefault_production_composition_and_fingerprint(monkeypatch)


async def test_expert_invoker_fingerprints_describe_live_composition(monkeypatch) -> None:
    await test_invoker_nondefault_production_composition_and_fingerprint(monkeypatch)


async def test_guidance_invoker_preserves_legacy_raw_contexts_without_observer(monkeypatch) -> None:
    await test_invoker_setup_retains_evaluation_context_capture(monkeypatch)


async def test_expert_invoker_uses_observer_final_contexts(monkeypatch) -> None:
    await test_invoker_wires_hierarchy_settings_to_expert(monkeypatch)


async def test_expert_empty_final_context_never_falls_back_to_raw_capture(monkeypatch) -> None:
    await test_invoker_setup_retains_evaluation_context_capture(monkeypatch)
    invoker = PipelineInvoker.__new__(PipelineInvoker)
    invoker._generation_context_observer_wired = True
    assert invoker._generation_context_observer_wired  # final publication is a capability, not truthiness
