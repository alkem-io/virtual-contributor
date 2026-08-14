"""In-process pipeline invocation for evaluation."""

from __future__ import annotations

import logging
import hashlib
import json

from core.config import BaseConfig
from core.container import Container, ContainerError
from core.events.input import Input
from core.ports.knowledge_store import KnowledgeStorePort
from core.ports.llm import LLMPort
from core.provider_factory import create_llm_adapter  # noqa: F401 - test seam
from core.registry import PluginRegistry
from evaluation.tracing import TracingKnowledgeStore

logger = logging.getLogger(__name__)


class PipelineInvoker:
    """Invokes the pipeline in-process for evaluation.

    Sets up the Container, resolves ports, wraps the KnowledgeStore
    with TracingKnowledgeStore, and calls the target plugin's handle().
    """

    def __init__(
        self,
        plugin_type: str,
        config: BaseConfig,
        body_of_knowledge_id: str | None = None,
    ) -> None:
        self._plugin_type = plugin_type
        self._config = config
        self._body_of_knowledge_id = body_of_knowledge_id
        self._plugin = None
        self._tracing_store: TracingKnowledgeStore | None = None
        self._llm_adapter = None
        self._composition_fingerprint = ""

    async def setup(self) -> None:
        """Initialize the pipeline: container, adapters, plugin."""
        from core.adapters.chromadb import ChromaDBAdapter

        # Production owns adapter and expert dependency composition. Evaluation
        # differs only by wrapping the already-composed store for transparent
        # capture, preventing a paired run from silently using other settings.
        from main import _create_adapters, _inject_answering_config, _inject_plugin_config

        container = Container()
        _create_adapters(self._config, container)
        try:
            store = container.resolve(KnowledgeStorePort)
        except ContainerError:
            container.register(KnowledgeStorePort, ChromaDBAdapter(
                host=self._config.vector_db_host or "localhost",
                port=self._config.vector_db_port,
            ))
            store = container.resolve(KnowledgeStorePort)
        self._llm_adapter = container.resolve(LLMPort)
        self._tracing_store = TracingKnowledgeStore(store)
        container.register(KnowledgeStorePort, self._tracing_store)

        # Discover and instantiate plugin
        registry = PluginRegistry()
        plugin_class = registry.discover(self._plugin_type)
        deps = container.resolve_for_plugin(plugin_class)
        signature = _inject_plugin_config(deps, plugin_class, self._config, None, None)
        _inject_answering_config(self._config, deps, signature)
        if "hybrid_config" in signature.parameters:
            deps["hybrid_config"] = self._config
        if "rerank_candidate_n" in signature.parameters:
            deps["rerank_candidate_n"] = self._config.rerank_candidate_n
        if "rerank_top_k" in signature.parameters:
            deps["rerank_top_k"] = self._config.rerank_top_k
        if "context_observer" in signature.parameters:
            deps["context_observer"] = self._tracing_store.capture_generation_context
        self._plugin = plugin_class(**deps)
        # Stable and redacted: this records all behavior-affecting evaluation
        # composition without serializing credentials, endpoints, or payloads.
        values = self._config.model_dump()
        effective = {
            key: value for key, value in values.items()
            if any(token in key for token in (
                "expert_", "hybrid_", "rerank_", "routing_", "query_rewrite",
                "answering_", "embeddings_", "vector_db_distance",
            )) and not any(secret in key for secret in ("key", "credentials", "endpoint"))
        }
        # A paired flat/on run is allowed to differ in this one experimental
        # toggle. All other composition drift invalidates the comparison.
        effective.pop("expert_hierarchical_retrieval_enabled", None)
        serialized = json.dumps(effective, sort_keys=True, default=str, separators=(",", ":"))
        self._composition_fingerprint = hashlib.sha256(serialized.encode()).hexdigest()

        await self._plugin.startup()
        logger.info("Pipeline initialized: plugin=%s", self._plugin_type)

    async def invoke(
        self, question: str
    ) -> tuple[str, list[str], list[dict]]:
        """Invoke the pipeline with a question.

        Returns:
            (pipeline_answer, retrieved_contexts, sources_metadata)
        """
        if self._plugin is None or self._tracing_store is None:
            raise RuntimeError("PipelineInvoker not set up. Call setup() first.")

        self._tracing_store.clear()

        event = Input.model_validate({
            "engine": self._plugin_type,
            "userID": "evaluation",
            "message": question,
            "personaID": "evaluation",
            "displayName": "Evaluation Runner",
            "bodyOfKnowledgeID": self._body_of_knowledge_id,
            "resultHandler": {
                "action": "none",
                "roomDetails": {
                    "roomID": "eval",
                    "actorID": "eval",
                    "threadID": "eval",
                    "vcInteractionID": "eval",
                },
            },
        })

        response = await self._plugin.handle(event)

        retrieved_contexts = self._tracing_store.get_final_detail_contexts()

        sources = []
        for src in response.sources:
            sources.append({
                "uri": src.uri,
                "title": src.title,
                "score": src.score,
            })

        return (response.result or "", retrieved_contexts, sources)

    @property
    def langchain_chat_model(self):
        """Access the raw LangChain BaseChatModel for RAGAS metric configuration."""
        if self._llm_adapter is None:
            raise RuntimeError("PipelineInvoker not set up. Call setup() first.")
        return self._llm_adapter._llm

    @property
    def composition_fingerprint(self) -> str:
        """Redacted hash of the effective production composition."""
        if not self._composition_fingerprint:
            raise RuntimeError("PipelineInvoker not set up. Call setup() first.")
        return self._composition_fingerprint

    async def shutdown(self) -> None:
        if self._plugin is not None:
            await self._plugin.shutdown()
