"""Evaluation remains independent of runtime tracing."""

import ast
from pathlib import Path

from core.config import BaseConfig
from core.ports.knowledge_store import QueryResult
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
