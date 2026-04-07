"""In-process pipeline invocation for evaluation."""

from __future__ import annotations

import logging

from core.config import BaseConfig
from core.container import Container
from core.events.input import Input
from core.ports.knowledge_store import KnowledgeStorePort
from core.ports.llm import LLMPort
from core.provider_factory import create_llm_adapter
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

    async def setup(self) -> None:
        """Initialize the pipeline: container, adapters, plugin."""
        from core.adapters.chromadb import ChromaDBAdapter

        # Create LLM adapter
        self._llm_adapter = create_llm_adapter(self._config)

        # Create knowledge store adapter
        ks_adapter = ChromaDBAdapter(
            host=self._config.vector_db_host or "localhost",
            port=self._config.vector_db_port,
            credentials=self._config.vector_db_credentials,
        )

        # Wrap with tracing
        self._tracing_store = TracingKnowledgeStore(ks_adapter)

        # Build container
        container = Container()
        container.register(LLMPort, self._llm_adapter)
        container.register(KnowledgeStorePort, self._tracing_store)

        # Discover and instantiate plugin
        registry = PluginRegistry()
        plugin_class = registry.discover(self._plugin_type)
        deps = container.resolve_for_plugin(plugin_class)
        self._plugin = plugin_class(**deps)

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

        retrieved_contexts = self._tracing_store.get_retrieved_contexts()

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

    async def shutdown(self) -> None:
        if self._plugin is not None:
            await self._plugin.shutdown()
