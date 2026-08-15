"""In-process pipeline invocation for evaluation."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from core.config import BaseConfig
from core.container import Container, ContainerError
from core.events.input import Input
from core.ports.knowledge_store import KnowledgeStorePort
from core.ports.llm import LLMPort
from core.provider_factory import create_llm_adapter  # noqa: F401 - test seam
from core.registry import PluginRegistry
from evaluation.tracing import TracingKnowledgeStore
from plugins.expert.composition import (
    ResolvedExpertComposition, expert_composition_fingerprint,
    ExpertPlumbing, expert_runtime_config, resolve_expert_composition,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExpertEvaluationIdentity:
    """Atomic public identity for a concrete Expert evaluation invocation."""

    hierarchy_mode: str
    invariant_composition_fingerprint: str
    full_composition_fingerprint: str

    def __post_init__(self) -> None:
        if self.hierarchy_mode not in {"flat", "hierarchical"}:
            raise ValueError("Expert evaluation identity has an invalid hierarchy mode")
        if any(
            len(value) != 64 or any(char not in "0123456789abcdef" for char in value)
            for value in (self.invariant_composition_fingerprint, self.full_composition_fingerprint)
        ):
            raise ValueError("Expert evaluation identity fingerprints must be SHA-256 digests")


def effective_composition_fingerprint(composition: ResolvedExpertComposition) -> str:
    """Hash redacted behavior-affecting composition for paired evaluation.

    The hierarchy retrieval toggle is the controlled experiment variable and
    deliberately does not alter the paired-run fingerprint. Display-name
    rendering remains included because it changes model-visible context.
    """
    return expert_composition_fingerprint(composition)


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
        self._plugin_type = plugin_type.lower().replace("-", "_")
        # Evaluation selection is authoritative before adapter construction.
        selected = config.model_copy(update={"plugin_type": self._plugin_type})
        self._config = selected
        self._expert_composition: ResolvedExpertComposition | None = None
        self._expert_plumbing: ExpertPlumbing | None = None
        self._body_of_knowledge_id = body_of_knowledge_id
        self._plugin = None
        self._tracing_store: TracingKnowledgeStore | None = None
        self._llm_adapter = None
        self._composition_fingerprint = ""
        self._full_composition_fingerprint = ""
        self._evaluation_identity: ExpertEvaluationIdentity | None = None
        self._generation_context_observer_wired = False

    async def setup(self) -> None:
        """Initialize the pipeline: container, adapters, plugin."""
        from core.adapters.chromadb import ChromaDBAdapter

        # Production owns adapter and expert dependency composition. Evaluation
        # differs only by wrapping the already-composed store for transparent
        # capture, preventing a paired run from silently using other settings.
        from main import (
            _compose_expert_dependencies,
            _create_adapters,
            _expert_composition_fingerprint,
        )

        if self._plugin_type == "expert":
            # This is the sole evaluation resolution and occurs before either
            # adapter or plugin factory.  The object is retained by identity.
            resolved_wiring = resolve_expert_composition(
                self._config, llm_config=__import__("main")._resolve_plugin_llm_config(self._config),
            )
            self._expert_composition, self._expert_plumbing = resolved_wiring.authority, resolved_wiring.plumbing
            self._config = expert_runtime_config(self._expert_composition, self._expert_plumbing)
        container = Container()
        _create_adapters(self._expert_composition or self._config, container, self._expert_plumbing)
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
        if self._plugin_type.lower().replace("-", "_") == "expert":
            assert self._expert_composition is not None
            assert self._expert_plumbing is not None
            _compose_expert_dependencies(
                self._expert_composition, deps, plugin_class,
                plumbing=self._expert_plumbing,
                context_observer=self._tracing_store.capture_generation_context,
            )
            self._generation_context_observer_wired = True
        else:
            from main import _inject_answering_config, _inject_plugin_config

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
        self._composition_fingerprint = (
            _expert_composition_fingerprint(self._expert_composition)
            if self._expert_composition is not None else ""
        )
        from plugins.expert.composition import expert_full_composition_fingerprint
        if self._expert_composition is not None:
            self._full_composition_fingerprint = expert_full_composition_fingerprint(
                self._composition_fingerprint, self._expert_composition.mode,
            )
        if self._plugin_type == "expert":
            assert self._expert_composition is not None
            self._evaluation_identity = ExpertEvaluationIdentity(
                hierarchy_mode=(
                    self._expert_composition.mode
                ),
                invariant_composition_fingerprint=self._composition_fingerprint,
                full_composition_fingerprint=self._full_composition_fingerprint,
            )

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

        retrieved_contexts = (
            self._tracing_store.get_final_detail_contexts()
            if self._generation_context_observer_wired
            else self._tracing_store.get_retrieved_contexts()
        )

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

    @property
    def full_composition_fingerprint(self) -> str:
        if not self._full_composition_fingerprint:
            raise RuntimeError("PipelineInvoker not set up. Call setup() first.")
        return self._full_composition_fingerprint

    @property
    def evaluation_identity(self) -> ExpertEvaluationIdentity:
        """Return the complete public Expert identity after setup."""
        if self._plugin_type != "expert" or self._evaluation_identity is None:
            raise RuntimeError("PipelineInvoker has no Expert evaluation identity")
        return self._evaluation_identity

    async def shutdown(self) -> None:
        if self._plugin is not None:
            await self._plugin.shutdown()
