"""Application entry point — bootstrap, wire, run."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import unicodedata
import os
import signal
from typing import Any
from contextlib import nullcontext
from urllib.parse import urlsplit, urlunsplit

from pydantic_settings import BaseSettings

from core.config import BaseConfig, IngestSpaceConfig
from core.container import Container
from core.domain.rerank import LexicalReranker
from core.domain.rule_classifier import RuleQueryClassifier
from core.domain.faithfulness import ContextSufficiencyValidator
from core.health import HealthServer
from core.logging import setup_logging
from core.ports.llm import LLMPort
from core.ports.embeddings import EmbeddingsPort
from core.ports.knowledge_store import KnowledgeStorePort
from core.ports.reranker import RerankerPort
from core.registry import PluginRegistry
from core.router import Router
from plugins.expert.composition import (
    ExpertPlumbing, ResolvedExpertComposition, ResolvedExpertSelectors,
    expert_composition_fingerprint,
    expert_runtime_config,
)

logger = logging.getLogger(__name__)
GENERIC_PIPELINE_ERROR = "Error: unable to process request"


def _is_embedding_error(exc: Exception) -> bool:
    """Embedding retry ownership ends at the adapter, never at RabbitMQ."""
    from core.ports.embeddings import EmbeddingError
    return isinstance(exc, EmbeddingError)


def _is_permanent_embedding_error(exc: Exception) -> bool:
    """Return whether a terminal embedding result can be acknowledged.

    Input and permanent provider failures have no useful broker-level recovery
    path.  Once the generic result has been published, acknowledge them rather
    than routing the request to the broker's rejected-message handling.
    Exhausted transient failures remain a rejected terminal delivery so broker
    policy can retain its operational signal, but they are never republished.
    """
    from core.ports.embeddings import EmbeddingInputError, EmbeddingPermanentError

    return isinstance(exc, (EmbeddingInputError, EmbeddingPermanentError))


def _mask_sensitive(name: str, value: object) -> str:
    """Mask API key values for logging."""
    if value is None:
        return "None"
    s = str(value)
    if "api_key" in name or "headers" in name:
        return s[:3] + "****" if len(s) > 3 else "****"
    if name.endswith(("_endpoint", "_url")):
        parsed = urlsplit(s)
        if parsed.username is not None or parsed.password is not None:
            host = parsed.hostname or ""
            if parsed.port is not None:
                host = f"{host}:{parsed.port}"
            return urlunsplit(parsed._replace(netloc=f"***@{host}"))
    return s


def _build_routing_table(
    config: BaseConfig,
    *,
    n_results: int,
    score_threshold: float,
    max_context_chars: int,
) -> dict:
    """Turn routing config into the per-route retrieval profiles.

    The plugin's OWN effective settings are passed in, not read from the
    deprecated globals. This matters: production sets `EXPERT_MIN_SCORE` and
    `GUIDANCE_MIN_SCORE` to 0.1 and never sets `RETRIEVAL_SCORE_THRESHOLD`, so
    building from the global would silently impose 0.3 on every routed query —
    tripling a threshold nobody configured, the moment routing was switched on.

    The moderate route deliberately mirrors those same settings: an
    unrecognised question falls back to it, and that fallback has to behave
    exactly as the plugin does today.
    """
    from core.domain.routing import RetrievalProfile
    from core.ports.query_router import RouteClass

    default_threshold = score_threshold
    return {
        RouteClass.CONVERSATIONAL: RetrievalProfile(
            retrieve=False,
            n_results=n_results,
            score_threshold=default_threshold,
            max_context_chars=max_context_chars,
        ),
        RouteClass.SIMPLE: RetrievalProfile(
            retrieve=True,
            # Never wider than what the plugin would have used anyway — a
            # simple query must not become slower than it is today.
            n_results=min(config.routing_simple_n_results, n_results),
            score_threshold=default_threshold,
            max_context_chars=max_context_chars,
        ),
        RouteClass.MODERATE: RetrievalProfile(
            retrieve=True,
            n_results=n_results,
            score_threshold=default_threshold,
            max_context_chars=max_context_chars,
        ),
        RouteClass.COMPLEX: RetrievalProfile(
            retrieve=True,
            # At least as wide as today, and never narrower: a complex
            # question must not see less than an unrouted one.
            n_results=max(config.routing_complex_n_results, n_results),
            score_threshold=default_threshold,
            max_context_chars=max(
                config.routing_complex_context_chars, max_context_chars,
            ),
        ),
    }


#: Acknowledgements that classify CONVERSATIONAL but may mean "yes, do it".
#:
#: The classifier deliberately excludes bare "yes", "no" and "sure" from its
#: conversational set, on the stated grounds that after *"Shall I list the
#: templates in this space?"* they are the shortest way to say *do it*. That
#: reasoning applies verbatim to these, which it does include. Skipping them
#: searches the vector store for the literal string "ok" instead of the offer
#: the member just accepted — a regression against develop, which rewrites it.
#:
#: Excluding them costs nothing: they fall through to being rewritten, exactly
#: as today. The gate only ever needs to be *right* about what it skips.
_AMBIGUOUS_ACKNOWLEDGEMENTS = frozenset({
    "ok", "okay", "k", "kk", "alright", "all right", "right",
    "will do", "later", "got it", "gotcha", "noted", "understood",
    "sounds good", "fine", "cool", "yep", "yeah", "yup",
})


class _ConversationalSkipPolicy:
    """Skip the rewrite only for turns that are entirely small talk.

    Wraps the adaptive-query classifier without the plugins knowing it exists.

    **Only CONVERSATIONAL is safe, and not even all of it.** Skipping SIMPLE as
    well looks tempting — it is roughly twice as fast — but SIMPLE covers
    anaphoric follow-ups like "show me those" and "the name of the lead", which
    are meaningless without the preceding turn: 9 of a 12-turn corpus broke.
    And within CONVERSATIONAL, the acknowledgements above are held back
    because they can be an affirmative answer to a question the VC just asked.

    What remains — "thanks", "cheers", "bye" — asserts that the member wants
    nothing looked up, which is what makes dropping the history safe.
    """

    def __init__(self, classifier: object, conversational: object) -> None:
        self._classifier = classifier
        self._conversational = conversational

    @staticmethod
    def _normalise(message: str) -> str:
        """Strip trailing punctuation of any kind before the membership test.

        A literal `!.?` set misses "ok," and "ok…" — and the whole point of the
        hold-back list is that it must not be trivially side-stepped by how
        someone happens to punctuate.
        """
        stripped = message.strip().lower()
        while stripped and unicodedata.category(stripped[-1]).startswith("P"):
            stripped = stripped[:-1].rstrip()
        return stripped

    def should_skip_rewrite(self, message: str) -> bool:
        if self._normalise(message) in _AMBIGUOUS_ACKNOWLEDGEMENTS:
            return False
        try:
            return self._classifier.classify(message).route is self._conversational
        except Exception as exc:
            # Never let the optimisation break the request it was optimising.
            logger.warning(
                "Rewrite policy failed, not skipping: error_type=%s", type(exc).__name__
            )
            return False


def _build_rewrite_policy() -> object | None:
    """Build the gate policy if the classifier is available, else None.

    The classifier ships on a separate, unmerged PR that sits in a multi-way
    pile-up on these same files. Guarding the import means this feature builds
    and runs on develop today and starts gating the moment that lands — with no
    merge-order dependency in either direction. Returning None disables only the
    skip: every turn is rewritten, exactly as before.
    """
    try:
        from core.domain.rule_classifier import RuleQueryClassifier
        from core.ports.query_router import RouteClass
    except ImportError:
        logger.info(
            "Query-rewrite gating requested but the query classifier is not "
            "available in this build; every turn with history will be rewritten"
        )
        return None
    return _ConversationalSkipPolicy(RuleQueryClassifier(), RouteClass.CONVERSATIONAL)


def _log_config(config: BaseConfig, plugin_class: type | None = None) -> None:
    """Log all configurable summarization/retrieval fields at startup.

    Ingest sizing is logged only for plugins that actually consume it — the
    log is the permanent detector for a silent sizing no-op, so reporting
    values a pipeline ignores would recreate exactly the false confidence it
    exists to prevent.
    """
    sizing_fields = {"chunk_size", "chunk_overlap", "summary_length"}
    consumed = (
        set(inspect.signature(plugin_class.__init__).parameters)
        if plugin_class is not None
        else sizing_fields
    )
    fields = [
        "summarize_llm_provider",
        "summarize_llm_model",
        "summarize_llm_api_key",
        "summarize_llm_temperature",
        "summarize_llm_timeout",
        "bok_llm_provider",
        "bok_llm_model",
        "bok_llm_api_key",
        "expert_n_results",
        "expert_min_score",
        "expert_hierarchical_retrieval_enabled",
        "expert_hierarchy_max_branches",
        "expert_hierarchy_display_names_enabled",
        "guidance_n_results",
        "guidance_min_score",
        "max_context_chars",
        "answering_llm_temperature",
        "answering_chain_of_thought_enabled",
        "hybrid_retrieval_enabled",
        "rerank_enabled",
        "rerank_candidate_n",
        "rerank_top_k",
        "rerank_lexical_weight",
        "routing_enabled",
        "routing_simple_n_results",
        "routing_complex_n_results",
        "routing_complex_context_chars",
        "faithfulness_validation_enabled",
        "query_rewrite_gating_enabled",
        "query_rewrite_max_expansion_ratio",
        # Explicitly non-secret query-safety controls.  These values are part
        # of the Expert v6 behaviour identity and are intentionally logged;
        # no endpoint, credential, environment or request data is added.
        "embeddings_query_max_utf8_bytes",
        "query_rewrite_max_utf8_bytes",
        "embeddings_max_attempts",
        "embeddings_attempt_timeout_seconds",
        "embeddings_total_deadline_seconds",
        "summary_chunk_threshold",
        "chunk_size",
        "chunk_overlap",
        "summary_length",
        "pipeline_timeout",
        "tracing_enabled",
        "tracing_otlp_headers",
        "tracing_service_name",
        "tracing_sample_ratio",
        "tracing_capture_content",
        "tracing_content_max_chars",
    ]
    for name in fields:
        if name in sizing_fields and name not in consumed:
            continue
        value = getattr(config, name, None)
        logger.info("Config: %s=%s", name.upper(), _mask_sensitive(name, value))


class _PluginTypeProbe(BaseSettings):
    """Reads only PLUGIN_TYPE, with the same env/.env binding as BaseConfig.

    Deliberately field-minimal: constructing a full BaseConfig to learn the
    plugin type would validate the ingest-space environment against the
    *shared* sizing defaults and abort startup on a legal configuration.
    """

    # Derived, not duplicated: if BaseConfig's env binding ever changes
    # (env_prefix, case_sensitive, secrets_dir), the probe must follow it or
    # plugin-type resolution silently diverges from the config it selects.
    model_config = BaseConfig.model_config

    plugin_type: str = ""


def _load_config() -> BaseConfig:
    """Load plugin-specific configuration when it has intentional overrides.

    The plugin type is read straight from the environment rather than from a
    probe ``BaseConfig()``: constructing the base class would validate the
    ingest-space environment against the *shared* defaults, so a legal
    ``CHUNK_OVERLAP`` between BaseConfig's chunk_size and IngestSpaceConfig's
    would abort startup with an error naming a size the operator never set.
    """
    # Resolve plugin_type through a minimal model that shares BaseConfig's
    # env_file binding: a raw os.environ read would miss a PLUGIN_TYPE set in
    # .env (a documented local-dev path) and silently load the wrong sizing.
    plugin_type = _PluginTypeProbe().plugin_type
    if plugin_type.lower() == "ingest-space":
        return IngestSpaceConfig()
    return BaseConfig()


def _inject_plugin_config(
    deps: dict[str, Any],
    plugin_class: type,
    config: BaseConfig,
    summarize_llm: LLMPort | None,
    bok_llm: LLMPort | None,
) -> inspect.Signature:
    """Inject configuration fields declared by a plugin constructor."""
    sig = inspect.signature(plugin_class.__init__)
    plugin_name = config.plugin_type.lower().replace("-", "_") if config.plugin_type else ""

    # Inject per-plugin retrieval config
    if "n_results" in sig.parameters:
        if plugin_name == "expert":
            deps["n_results"] = config.expert_n_results
        elif plugin_name == "guidance":
            deps["n_results"] = config.guidance_n_results
        else:
            deps["n_results"] = config.retrieval_n_results
    if "score_threshold" in sig.parameters:
        if plugin_name == "expert":
            deps["score_threshold"] = config.expert_min_score
        elif plugin_name == "guidance":
            deps["score_threshold"] = config.guidance_min_score
        else:
            deps["score_threshold"] = config.retrieval_score_threshold
    if "max_context_chars" in sig.parameters:
        deps["max_context_chars"] = config.max_context_chars
    if "hierarchical_retrieval_enabled" in sig.parameters:
        deps["hierarchical_retrieval_enabled"] = (
            config.expert_hierarchical_retrieval_enabled
        )
    if "hierarchy_max_branches" in sig.parameters:
        deps["hierarchy_max_branches"] = config.expert_hierarchy_max_branches
    if "hierarchy_display_names_enabled" in sig.parameters:
        deps["hierarchy_display_names_enabled"] = (
            config.expert_hierarchy_display_names_enabled
        )
    if "embedding_query_max_utf8_bytes" in sig.parameters:
        deps["embedding_query_max_utf8_bytes"] = config.embeddings_query_max_utf8_bytes
    if "rewrite_max_utf8_bytes" in sig.parameters:
        deps["rewrite_max_utf8_bytes"] = config.query_rewrite_max_utf8_bytes

    # Inject summarization configuration for ingest plugins
    if "summarize_llm" in sig.parameters:
        deps["summarize_llm"] = summarize_llm
    if "bok_llm" in sig.parameters:
        deps["bok_llm"] = bok_llm
    if "chunk_threshold" in sig.parameters:
        deps["chunk_threshold"] = config.summary_chunk_threshold
    if "summarize_enabled" in sig.parameters:
        deps["summarize_enabled"] = config.summarize_enabled
    if "summarize_concurrency" in sig.parameters:
        deps["summarize_concurrency"] = config.summarize_concurrency
    if "ingest_batch_size" in sig.parameters:
        deps["ingest_batch_size"] = config.ingest_batch_size
    if "chunk_size" in sig.parameters:
        deps["chunk_size"] = config.chunk_size
    if "chunk_overlap" in sig.parameters:
        deps["chunk_overlap"] = config.chunk_overlap
    if "summary_length" in sig.parameters:
        deps["summary_length"] = config.summary_length

    return sig
def _inject_answering_config(
    config: BaseConfig, deps: dict[str, object], signature: inspect.Signature
) -> None:
    """Inject answering-only settings only into plugins that declare them."""

    if "answering_temperature" in signature.parameters:
        deps["answering_temperature"] = config.answering_llm_temperature
    if "chain_of_thought_enabled" in signature.parameters:
        deps["chain_of_thought_enabled"] = config.answering_chain_of_thought_enabled


def _compose_expert_dependencies(
    composition: ResolvedExpertComposition,
    deps: dict[str, Any],
    plugin_class: type,
    *,
    plumbing: ExpertPlumbing,
    selectors: ResolvedExpertSelectors,
    context_observer: object | None = None,
) -> inspect.Signature:
    """Apply every Expert setting at the one production/evaluation boundary."""
    # The transient view feeds legacy helper signatures only; every Expert
    # constructor kwarg below is explicitly read from immutable authority.
    config = expert_runtime_config(composition, plumbing)
    sig = _inject_plugin_config(deps, plugin_class, config, None, None)
    _inject_answering_config(config, deps, sig)
    if "hybrid_config" in sig.parameters:
        deps["hybrid_config"] = composition
    if "hybrid_retriever" in sig.parameters:
        deps["hybrid_retriever"] = selectors.entry("hybrid").target
    if "reranker" in deps:
        if "rerank_candidate_n" in sig.parameters:
            deps["rerank_candidate_n"] = config.rerank_candidate_n
        if "rerank_top_k" in sig.parameters:
            deps["rerank_top_k"] = config.rerank_top_k
    if config.routing_enabled and "query_router" in sig.parameters:
        deps["query_router"] = selectors.entry("router").target()
        if "routing_table" in sig.parameters:
            deps["routing_table"] = selectors.entry("routing_table").target(
                composition,
                n_results=deps.get("n_results", config.expert_n_results),
                score_threshold=deps.get("score_threshold", config.expert_min_score),
                max_context_chars=deps.get("max_context_chars", config.max_context_chars),
            )
    if "faithfulness_validator" in sig.parameters:
        deps["faithfulness_validator"] = (
            selectors.entry("faithfulness").target()
            if config.faithfulness_validation_enabled else None
        )
    if "max_expansion_ratio" in sig.parameters:
        deps["max_expansion_ratio"] = config.query_rewrite_max_expansion_ratio
    if "max_history_turns" in sig.parameters:
        plugin_history = getattr(config, "history_length", None)
        turns = config.query_rewrite_max_history_turns
        deps["max_history_turns"] = min(turns, plugin_history) if plugin_history else turns
    if "max_history_chars" in sig.parameters:
        deps["max_history_chars"] = config.query_rewrite_max_history_chars
    if "rewrite_policy" in sig.parameters and config.query_rewrite_gating_enabled:
        policy = selectors.entry("rewrite").target()
        if policy is not None:
            deps["rewrite_policy"] = policy
    if context_observer is not None and "context_observer" in sig.parameters:
        deps["context_observer"] = context_observer
    return sig


def _expert_composition_fingerprint(composition: ResolvedExpertComposition) -> str:
    """Serialize the already-resolved Expert authority; never reread config."""
    return expert_composition_fingerprint(composition)


def _resolve_plugin_llm_config(config: BaseConfig) -> BaseConfig:
    """Check for per-plugin LLM overrides via {PLUGIN_NAME}_LLM_* env vars.

    If plugin-specific env vars are set, they override global LLM_* values.
    Falls back to global config for any unset plugin-specific vars.
    """
    import os

    plugin_name = config.plugin_type.upper().replace("-", "_") if config.plugin_type else ""
    if not plugin_name:
        return config

    overrides: dict[str, str] = {}
    env_mappings = {
        "LLM_PROVIDER": "llm_provider",
        "LLM_API_KEY": "llm_api_key",
        "LLM_MODEL": "llm_model",
        "LLM_BASE_URL": "llm_base_url",
        "LLM_TEMPERATURE": "llm_temperature",
        "LLM_MAX_TOKENS": "llm_max_tokens",
        "LLM_TOP_P": "llm_top_p",
    }

    has_overrides = False
    for env_suffix, field_name in env_mappings.items():
        env_var = f"{plugin_name}_{env_suffix}"
        value = os.environ.get(env_var)
        if value is not None:
            overrides[field_name] = value
            has_overrides = True

    if not has_overrides:
        return config

    # Create a new config with overrides applied on top of global values
    merged = config.model_dump()
    merged.update(overrides)
    return BaseConfig(**merged)


def _create_adapters(
    config: BaseConfig | ResolvedExpertComposition, container: Container,
    plumbing: ExpertPlumbing | None = None,
    selectors: ResolvedExpertSelectors | None = None,
) -> None:
    """Wire adapter instances into the container based on config."""
    composition = config if isinstance(config, ResolvedExpertComposition) else None
    runtime_config: BaseConfig
    if composition is not None:
        runtime_config = expert_runtime_config(composition, plumbing or ExpertPlumbing(()))
    else:
        assert isinstance(config, BaseConfig)
        runtime_config = config
    config = runtime_config
    # LLM adapter — unified provider factory with per-plugin override support
    from core.provider_factory import create_llm_adapter

    effective_config = config if composition is not None else _resolve_plugin_llm_config(config)
    llm_factory = selectors.entry("llm").target if selectors is not None else create_llm_adapter
    llm_adapter = llm_factory(effective_config)
    container.register(LLMPort, llm_adapter)
    logger.info(
        "LLM provider configured: %s | model: %s",
        effective_config.llm_provider.value,
        effective_config.llm_model or "default",
    )

    # Embeddings adapters
    if config.embeddings_api_key and config.embeddings_endpoint:
        from core.adapters.openai_compatible_embeddings import OpenAICompatibleEmbeddingsAdapter

        embeddings_factory = (
            selectors.entry("embeddings").target
            if selectors is not None else OpenAICompatibleEmbeddingsAdapter
        )

        container.register(
            EmbeddingsPort,
            embeddings_factory(
                api_key=config.embeddings_api_key,
                endpoint=config.embeddings_endpoint,
                model_name=config.embeddings_model_name or "qwen3-embedding-8b",
                query_instruction=config.embeddings_query_instruction,
                query_max_utf8_bytes=config.embeddings_query_max_utf8_bytes,
                max_attempts=config.embeddings_max_attempts,
                attempt_timeout_seconds=config.embeddings_attempt_timeout_seconds,
                total_deadline_seconds=config.embeddings_total_deadline_seconds,
            ),
        )

    # Knowledge store
    if config.vector_db_host:
        from core.adapters.chromadb import ChromaDBAdapter

        store_factory = (
            selectors.entry("knowledge_store").target
            if selectors is not None else ChromaDBAdapter
        )

        embeddings_adapter = container._bindings.get(EmbeddingsPort)
        knowledge_store: KnowledgeStorePort = store_factory(
            host=config.vector_db_host,
            port=config.vector_db_port,
            credentials=config.vector_db_credentials,
            embeddings=embeddings_adapter,
            distance_fn=config.vector_db_distance_fn,
        )
        if config.tracing_enabled:
            from core.tracing import tracing_is_configured

            if tracing_is_configured():
                from core.tracing_knowledge_store import TracedKnowledgeStore

                knowledge_store = TracedKnowledgeStore(knowledge_store)
        container.register(KnowledgeStorePort, knowledge_store)

    # OpenAI Assistants (always available — per-request API keys)
    from core.adapters.openai_assistant import OpenAIAssistantAdapter

    container.register(OpenAIAssistantAdapter, OpenAIAssistantAdapter())

    # Re-ranker — registered only when enabled. Left unregistered, plugins
    # keep their `reranker=None` default and never take the re-ranking path,
    # which is what makes disabling it a true rollback rather than a second
    # code path that merely resembles the old one.
    if config.rerank_enabled:
        reranker_factory = selectors.entry("reranker").target if selectors is not None else LexicalReranker
        container.register(
            RerankerPort,
            reranker_factory(lexical_weight=config.rerank_lexical_weight),
        )


async def _shutdown_tracing_bounded() -> None:
    """Flush tracing without allowing an unreachable collector to delay exit.

    A daemon thread (not asyncio.to_thread) bounds PROCESS exit, not just the
    event loop: to_thread uses a non-daemon executor worker, which keeps the
    interpreter alive until the SDK's unbounded flush finishes — measured
    10-40s against a dead collector, overshooting k8s' 30s grace period.
    """
    import threading

    from core.tracing import shutdown_tracing

    flusher = threading.Thread(target=shutdown_tracing, daemon=True, name="tracing-flush")
    flusher.start()
    deadline = 5.0
    while flusher.is_alive() and deadline > 0:
        await asyncio.sleep(0.1)
        deadline -= 0.1
    if flusher.is_alive():
        logger.warning("Tracing shutdown exceeded 5s; closing transport anyway")


def build_message_handler(
    *,
    config: BaseConfig,
    plugin: object,
    router: Router,
    transport: object,
    active_tasks: set,
):
    """Build the production on_message handler (module-level so tests can
    drive the REAL wiring — root spans, failure taxonomy, both ACK paths —
    instead of re-implementing it)."""

    def _is_ingest_event(event: object) -> bool:
        """Return True for ingest event types that should use early ACK."""
        from core.events.ingest_space import IngestBodyOfKnowledge
        from core.events.ingest_website import IngestWebsite
        return isinstance(event, (IngestWebsite, IngestBodyOfKnowledge))

    async def _publish_result(envelope: dict) -> None:
        """Publish a result envelope to the result queue."""
        await transport.publish(
            config.rabbitmq_exchange,
            config.rabbitmq_result_routing_key,
            json.dumps(envelope).encode("utf-8"),
        )

    async def _run_pipeline(event: object) -> None:
        """Run plugin.handle() with timeout and publish result."""
        from core.tracing import (
            FailureMode,
            LLMInvocationTimeoutError,
            classify_failure,
            handle_span,
            record_failure,
            tracing_is_configured,
        )

        context = handle_span(config, event, plugin.name) if tracing_is_configured() else nullcontext(None)
        with context as root:
            try:
                response = await asyncio.wait_for(
                    plugin.handle(event),
                    timeout=config.pipeline_timeout,
                )
                envelope = router.build_response_envelope(response, event)
                await _publish_result(envelope)
                if root is not None:
                    from opentelemetry import trace

                    # Early-ACK events have already acknowledged delivery;
                    # retain the same success-only structural ordering for
                    # future message-bearing early-ACK event types.
                    from core.tracing import set_content_attribute
                    set_content_attribute(root, "vc.message", getattr(event, "message", None), config)
                    root.set_status(trace.Status(trace.StatusCode.OK))
            except LLMInvocationTimeoutError as exc:
                logger.error(
                    "LLM provider timed out for event type %s", type(event).__name__
                )
                if root is not None:
                    record_failure(root, exc, FailureMode.llm_error, config=config)
                from core.events.response import Response
                error_response = Response(result=GENERIC_PIPELINE_ERROR)
                envelope = router.build_response_envelope(error_response, event)
                try:
                    await _publish_result(envelope)
                except Exception as publish_exc:
                    logger.error("Early-ACK fallback publication failed: error_type=%s", type(publish_exc).__name__)
            except asyncio.TimeoutError as exc:
                logger.error(
                    "Pipeline timed out after %ds for event type %s",
                    config.pipeline_timeout,
                    type(event).__name__,
                )
                if root is not None:
                    record_failure(root, exc, FailureMode.timeout, config=config)
                from core.events.response import Response
                error_response = Response(result=GENERIC_PIPELINE_ERROR)
                envelope = router.build_response_envelope(error_response, event)
                try:
                    await _publish_result(envelope)
                except Exception as publish_exc:
                    logger.error("Early-ACK fallback publication failed: error_type=%s", type(publish_exc).__name__)
            except Exception as exc:
                logger.error("Pipeline failed for event type %s: error_type=%s", type(event).__name__, type(exc).__name__)
                if root is not None:
                    record_failure(root, exc, classify_failure(exc), config=config)
                from core.events.response import Response
                error_response = Response(result=GENERIC_PIPELINE_ERROR)
                envelope = router.build_response_envelope(error_response, event)
                try:
                    await _publish_result(envelope)
                except Exception as publish_exc:
                    logger.error("Early-ACK fallback publication failed: error_type=%s", type(publish_exc).__name__)

    def _task_done(task: asyncio.Task) -> None:
        """Retrieve every early-ACK terminal state without rendering it."""
        active_tasks.discard(task)
        if task.cancelled():
            logger.warning("Early-ACK background task cancelled")
            return
        try:
            task.result()
        except Exception as exc:
            # Never pass the exception object to logging: its message, cause
            # and traceback may contain ingest content or provider details.
            logger.error("Early-ACK background task failed: error_type=%s", type(exc).__name__)

    # Message handler — receives both body and raw message for ACK control
    async def on_message(
        body: dict,
        message: object,
    ) -> None:
        try:
            event = router.parse_event(body)
        except Exception as exc:
            # Parsing is the only operation that can enter raw-message retry.
            logger.error("Failed to parse message: error_type=%s", type(exc).__name__)
            await _retry_or_reject(message, body)
            return

        if _is_ingest_event(event):
            # Early ACK: acknowledge before processing starts
            await message.ack()  # type: ignore[union-attr]
            logger.info(
                "Early-ACKed ingest message, scheduling async pipeline for %s",
                type(event).__name__,
            )
            task = asyncio.create_task(_run_pipeline(event))
            active_tasks.add(task)
            task.add_done_callback(_task_done)
            return

        # Engine query: explicit terminal delivery state.  A terminal result
        # may be published exactly once; ACK failure must not re-enter raw
        # retry and therefore cannot re-execute a member request.
        from core.tracing import (
            FailureMode,
            LLMInvocationTimeoutError,
            classify_failure,
            handle_span,
            record_failure,
            tracing_is_configured,
        )
        context = handle_span(config, event, plugin.name) if tracing_is_configured() else nullcontext(None)
        delivery_state = "unpublished"
        with context as root:
            try:
                response = await asyncio.wait_for(
                    plugin.handle(event), timeout=config.pipeline_timeout,
                )
                envelope = router.build_response_envelope(response, event)
                await _publish_result(envelope)
            except LLMInvocationTimeoutError as exc:
                logger.error("LLM provider timed out for %s", type(event).__name__)
                if root is not None:
                    record_failure(root, exc, FailureMode.llm_error, config=config)
                await _retry_or_reject(message, body, event=event, error_text=GENERIC_PIPELINE_ERROR)
                return
            except asyncio.TimeoutError as exc:
                logger.error("Handler timed out after %ds for %s", config.pipeline_timeout, type(event).__name__)
                if root is not None:
                    record_failure(root, exc, FailureMode.timeout, config=config)
                await _retry_or_reject(message, body, event=event, error_text=f"Error: handler timed out after {config.pipeline_timeout}s")
                return
            except Exception as exc:
                logger.error("Engine query failed: error_type=%s", type(exc).__name__)
                if root is not None:
                    record_failure(root, exc, classify_failure(exc), config=config)
                await _retry_or_reject(
                    message, body, event=event, error_text=GENERIC_PIPELINE_ERROR,
                    force_terminal=_is_embedding_error(exc),
                    acknowledge_terminal=_is_permanent_embedding_error(exc),
                )
                return

            delivery_state = "published-unacked"
            try:
                await message.ack()  # type: ignore[union-attr]
            except Exception as exc:
                logger.error("Terminal result ACK failed: error_type=%s", type(exc).__name__)
                if root is not None:
                    record_failure(root, exc, classify_failure(exc), config=config)
                return
            delivery_state = "settled"
            if root is not None:
                from opentelemetry import trace
                from core.tracing import set_content_attribute
                set_content_attribute(root, "vc.message", getattr(event, "message", None), config)
                root.set_status(trace.Status(trace.StatusCode.OK))

        # Keep the terminal states explicit and inspectable in the handler
        # source without adding user or broker data to logs/spans.
        assert delivery_state == "settled"
        return

    async def _retry_or_reject(
        message: object,
        body: dict,
        *,
        event: object | None = None,
        error_text: str | None = None,
        force_terminal: bool = False,
        acknowledge_terminal: bool = False,
    ) -> None:
        """Requeue for another attempt or publish a final error.

        Intermediate retries stay silent — publishing on every attempt
        would spam the room with failure messages.  Only on the last
        attempt do we emit ``error_text`` as the response so the user
        gets closure.
        """
        headers = getattr(message, "headers", None) or {}
        retry_count = int(headers.get("x-retry-count", 0))
        max_retries = config.rabbitmq_max_retries

        if not force_terminal and retry_count < max_retries - 1:
            logger.warning(
                "Message failed (attempt %d/%d), requeuing",
                retry_count + 1, max_retries,
            )
            new_headers = dict(headers)
            new_headers["x-retry-count"] = retry_count + 1
            try:
                await transport.republish_with_headers(
                    config.rabbitmq_input_queue,
                    json.dumps(body).encode("utf-8"),
                    new_headers,
                )
            except Exception as pub_exc:
                logger.error("Failed to republish retry message: error_type=%s", type(pub_exc).__name__)
                # Republish failed — the message will be lost after reject.
                # Publish the error response now so the user isn't left hanging.
                if event is not None and error_text:
                    try:
                        from core.events.response import Response
                        error_response = Response(result=error_text)
                        envelope = router.build_response_envelope(
                            error_response, event,
                        )
                        await _publish_result(envelope)
                    except Exception:
                        logger.error("Failed to publish fallback error response")
            try:
                await message.reject(requeue=False)  # type: ignore[union-attr]
            except Exception as reject_exc:
                logger.error(
                    "Retry reject settlement failed: error_type=%s",
                    type(reject_exc).__name__, exc_info=False,
                )
        else:
            logger.error(
                "Message terminal after %d/%d attempts (forced=%s), discarding",
                retry_count + 1, max_retries, force_terminal,
            )
            terminal_published = False
            if event is not None and error_text:
                try:
                    from core.events.response import Response
                    error_response = Response(result=error_text)
                    envelope = router.build_response_envelope(
                        error_response, event,
                    )
                    await _publish_result(envelope)
                    terminal_published = True
                except Exception as pub_exc:
                    logger.error("Failed to publish terminal error response: error_type=%s", type(pub_exc).__name__)
            # A terminal result is an actual delivery state: ACK only after
            # confirmation.  On failed result publication retain broker-owned
            # disposition rather than losing the only response.
            if acknowledge_terminal and terminal_published:
                try:
                    await message.ack()  # type: ignore[union-attr]
                except Exception as ack_exc:
                    # The result is terminally published; raw retry here would
                    # duplicate plugin execution and response delivery.
                    logger.error("Terminal error-result ACK failed: error_type=%s", type(ack_exc).__name__)
            else:
                try:
                    await message.reject(requeue=False)  # type: ignore[union-attr]
                except Exception as reject_exc:
                    logger.error(
                        "Terminal reject settlement failed: error_type=%s",
                        type(reject_exc).__name__, exc_info=False,
                    )

    return on_message


async def _run(config: BaseConfig) -> None:
    """Main async entrypoint."""
    from core.adapters.rabbitmq import RabbitMQAdapter

    # Expert resolves effective defaults once before any adapter or plugin
    # factory.  The same view is later used for live wiring and identity.
    expert_composition: ResolvedExpertComposition | None = None
    expert_plumbing: ExpertPlumbing | None = None
    expert_selectors: ResolvedExpertSelectors | None = None
    if config.plugin_type.lower().replace("-", "_") == "expert":
        from plugins.expert.composition import resolve_expert_composition
        resolved_wiring = resolve_expert_composition(
            config, llm_config=_resolve_plugin_llm_config(config),
        )
        expert_composition, expert_plumbing, expert_selectors = (
            resolved_wiring.authority, resolved_wiring.plumbing, resolved_wiring.selectors,
        )
        config = expert_runtime_config(expert_composition, expert_plumbing)

    # Discover plugin
    registry = PluginRegistry()
    plugin_class = registry.discover(config.plugin_type)
    logger.info("Discovered plugin: %s", plugin_class.name)

    # Wire adapters
    container = Container()
    _create_adapters(expert_composition or config, container, expert_plumbing, expert_selectors)

    # Create summarization LLM adapter if fully configured
    summarize_llm = None
    summarize_fields = [
        config.summarize_llm_provider,
        config.summarize_llm_model,
        config.summarize_llm_api_key,
    ]
    if all(f is not None for f in summarize_fields):
        from core.provider_factory import create_llm_adapter

        # Build a synthetic config mapping summarize_llm_* to llm_* fields
        synth_data = config.model_dump()
        synth_data["llm_provider"] = config.summarize_llm_provider
        synth_data["llm_model"] = config.summarize_llm_model
        synth_data["llm_api_key"] = config.summarize_llm_api_key
        synth_data["llm_temperature"] = (
            config.summarize_llm_temperature
            if config.summarize_llm_temperature is not None
            else 0.3
        )
        if config.summarize_llm_base_url is not None:
            synth_data["llm_base_url"] = config.summarize_llm_base_url
        if config.summarize_llm_timeout is not None:
            synth_data["llm_timeout"] = config.summarize_llm_timeout
        summarize_llm = create_llm_adapter(
            BaseConfig(**synth_data), disable_thinking=True
        )
        logger.info(
            "Summarization LLM configured: provider=%s, model=%s, endpoint=%s",
            config.summarize_llm_provider.value,
            config.summarize_llm_model,
            "configured" if config.summarize_llm_base_url else "inherited",
        )

    # Create BoK LLM adapter if fully configured (needs large context window)
    bok_llm = None
    bok_fields = [
        config.bok_llm_provider,
        config.bok_llm_model,
        config.bok_llm_api_key,
    ]
    if all(f is not None for f in bok_fields):
        synth_data = config.model_dump()
        synth_data["llm_provider"] = config.bok_llm_provider
        synth_data["llm_model"] = config.bok_llm_model
        synth_data["llm_api_key"] = config.bok_llm_api_key
        synth_data["llm_temperature"] = (
            config.bok_llm_temperature
            if config.bok_llm_temperature is not None
            else 0.3
        )
        if config.bok_llm_base_url is not None:
            synth_data["llm_base_url"] = config.bok_llm_base_url
        if config.bok_llm_timeout is not None:
            synth_data["llm_timeout"] = config.bok_llm_timeout
        bok_llm = create_llm_adapter(BaseConfig(**synth_data), disable_thinking=True)
        logger.info(
            "BoK LLM configured: provider=%s, model=%s, endpoint=%s",
            config.bok_llm_provider.value,
            config.bok_llm_model,
            "configured" if config.bok_llm_base_url else "inherited",
        )

    # Construct plugin with dependencies
    deps = container.resolve_for_plugin(plugin_class)
    plugin_name = config.plugin_type.lower().replace("-", "_") if config.plugin_type else ""
    expert_composed = plugin_name == "expert"
    if expert_composed:
        assert expert_composition is not None
        assert expert_plumbing is not None
        assert expert_selectors is not None
        sig = _compose_expert_dependencies(
            expert_composition, deps, plugin_class,
            plumbing=expert_plumbing, selectors=expert_selectors,
        )
    else:
        sig = _inject_plugin_config(
            deps, plugin_class, config, summarize_llm, bok_llm,
        )
    # Non-Expert plugins retain their established, plugin-generic wiring.
    if not expert_composed and "n_results" in sig.parameters:
        if plugin_name == "expert":
            deps["n_results"] = config.expert_n_results
        elif plugin_name == "guidance":
            deps["n_results"] = config.guidance_n_results
        else:
            deps["n_results"] = config.retrieval_n_results
    if not expert_composed and "score_threshold" in sig.parameters:
        if plugin_name == "expert":
            deps["score_threshold"] = config.expert_min_score
        elif plugin_name == "guidance":
            deps["score_threshold"] = config.guidance_min_score
        else:
            deps["score_threshold"] = config.retrieval_score_threshold
    if not expert_composed and "max_context_chars" in sig.parameters:
        deps["max_context_chars"] = config.max_context_chars
    if not expert_composed:
        _inject_answering_config(config, deps, sig)
    # The whole config object, so the retrieval helper reads the hybrid
    # settings from one place rather than each plugin re-listing them.
    if not expert_composed and "hybrid_config" in sig.parameters:
        deps["hybrid_config"] = config
    # The re-ranker itself now arrives via `resolve_for_plugin` above, which
    # resolves the `RerankerPort | None` annotation to the registration made
    # in `_create_adapters`. Only its scalar settings still need injecting,
    # and only when it is actually present — otherwise a disabled deployment
    # would carry re-ranking numbers it never uses.
    if not expert_composed and "reranker" in deps:
        if "rerank_candidate_n" in sig.parameters:
            deps["rerank_candidate_n"] = config.rerank_candidate_n
        if "rerank_top_k" in sig.parameters:
            deps["rerank_top_k"] = config.rerank_top_k
    # Inject the classifier only when routing is enabled. Left absent, the
    # plugins keep their `query_router=None` default and take their existing
    # code path — which is what makes disabling this a true rollback rather
    # than a routing table that merely happens to agree with today.
    if not expert_composed and config.routing_enabled and "query_router" in sig.parameters:
        deps["query_router"] = RuleQueryClassifier()
        if "routing_table" in sig.parameters:
            deps["routing_table"] = _build_routing_table(
                config,
                n_results=deps.get("n_results", config.retrieval_n_results),
                score_threshold=deps.get(
                    "score_threshold", config.retrieval_score_threshold,
                ),
                max_context_chars=deps.get(
                    "max_context_chars", config.max_context_chars,
                ),
            )
    # None means disabled, and is checked before any validation code runs — so
    # disabling is a structural absence rather than a branch inside the check.
    if not expert_composed and "faithfulness_validator" in sig.parameters:
        deps["faithfulness_validator"] = (
            ContextSufficiencyValidator()
            if config.faithfulness_validation_enabled
            else None
        )
    # Inject the query-rewrite gate
    if not expert_composed and "max_expansion_ratio" in sig.parameters:
        deps["max_expansion_ratio"] = config.query_rewrite_max_expansion_ratio
    if not expert_composed and "max_history_turns" in sig.parameters:
        # Honour a plugin's own `history_length` when it declares one — it is
        # that plugin's statement about how much history is meaningful, and it
        # should never be exceeded by the rewrite prompt.
        plugin_history = getattr(config, "history_length", None)
        turns = config.query_rewrite_max_history_turns
        deps["max_history_turns"] = (
            min(turns, plugin_history) if plugin_history else turns
        )
    if not expert_composed and "max_history_chars" in sig.parameters:
        deps["max_history_chars"] = config.query_rewrite_max_history_chars
    if (not expert_composed and "rewrite_policy" in sig.parameters
            and config.query_rewrite_gating_enabled):
        policy = _build_rewrite_policy()
        if policy is not None:
            deps["rewrite_policy"] = policy
    # Inject summarization LLM for ingest plugins
    if "summarize_llm" in sig.parameters:
        deps["summarize_llm"] = summarize_llm
    # Inject BoK LLM for ingest plugins (large-context model for BoK summary)
    if "bok_llm" in sig.parameters:
        deps["bok_llm"] = bok_llm
    # Inject chunk threshold for ingest plugins
    if "chunk_threshold" in sig.parameters:
        deps["chunk_threshold"] = config.summary_chunk_threshold
    # Inject summarization toggle and concurrency for ingest plugins
    if "summarize_enabled" in sig.parameters:
        deps["summarize_enabled"] = config.summarize_enabled
    if "summarize_concurrency" in sig.parameters:
        deps["summarize_concurrency"] = config.summarize_concurrency
    if "ingest_batch_size" in sig.parameters:
        deps["ingest_batch_size"] = config.ingest_batch_size
    # Inject GraphQL client for ingest-space plugin
    if "graphql_client" in sig.parameters:
        from plugins.ingest_space.graphql_client import GraphQLClient
        gql_endpoint = getattr(config, "api_endpoint_private_graphql", "") or os.environ.get("API_ENDPOINT_PRIVATE_GRAPHQL", "")
        kratos_url = getattr(config, "auth_kratos_public_url", "") or os.environ.get("AUTH_ORY_KRATOS_PUBLIC_BASE_URL", "")
        admin_email = getattr(config, "auth_admin_email", "") or os.environ.get("AUTH_ADMIN_EMAIL", "")
        admin_password = getattr(config, "auth_admin_password", "") or os.environ.get("AUTH_ADMIN_PASSWORD", "")
        if gql_endpoint and admin_email and admin_password:
            deps["graphql_client"] = GraphQLClient(
                graphql_endpoint=gql_endpoint,
                kratos_public_url=kratos_url,
                email=admin_email,
                password=admin_password,
            )
            logger.info("GraphQL client configured")
        else:
            logger.warning("GraphQL client not configured — missing API_ENDPOINT_PRIVATE_GRAPHQL, AUTH_ADMIN_EMAIL, or AUTH_ADMIN_PASSWORD")
    plugin = plugin_class(**deps)
    if expert_composed:
        assert expert_composition is not None
        logger.info(
            "Expert composition fingerprint=%s",
            _expert_composition_fingerprint(expert_composition),
        )

    # Plugin lifecycle: startup
    await plugin.startup()
    logger.info("Plugin %s started", plugin.name)

    # Transport
    transport = RabbitMQAdapter(
        host=config.rabbitmq_host,
        port=config.rabbitmq_port,
        user=config.rabbitmq_user,
        password=config.rabbitmq_password,
        exchange_name=config.rabbitmq_exchange,
        heartbeat=config.rabbitmq_heartbeat,
        max_retries=config.rabbitmq_max_retries,
    )
    await transport.connect()

    # Router
    router = Router(plugin_type=config.plugin_type)

    # Track in-flight pipeline tasks for graceful shutdown
    active_tasks: set[asyncio.Task] = set()

    on_message = build_message_handler(
        config=config,
        plugin=plugin,
        router=router,
        transport=transport,
        active_tasks=active_tasks,
    )

    # Start consuming with message handle exposed for ACK control
    await transport.consume_with_message(config.rabbitmq_input_queue, on_message)

    # Health server
    health = HealthServer(port=config.health_port)
    health.add_check("rabbitmq", transport.is_connected)
    health.add_check("plugin", lambda: True)
    await health.start()

    logger.info("Engine ready — consuming")

    # Shutdown handling
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        logger.info("Shutdown signal received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _signal_handler)

    await stop_event.wait()

    # Graceful shutdown
    logger.info("Shutting down...")

    # Wait for in-flight pipeline tasks to complete (30s grace period)
    if active_tasks:
        logger.info(
            "Waiting for %d in-flight pipeline task(s) to complete (30s grace)...",
            len(active_tasks),
        )
        done, pending = await asyncio.wait(active_tasks, timeout=30)
        if pending:
            logger.warning(
                "Cancelling %d pipeline task(s) that did not complete in time",
                len(pending),
            )
            for task in pending:
                task.cancel()
            # Wait briefly for cancellation to propagate
            await asyncio.wait(pending, timeout=5)

    await health.stop()
    await plugin.shutdown()
    await _shutdown_tracing_bounded()
    await transport.close()
    logger.info("Shutdown complete")


def main() -> None:
    import concurrent.futures

    config = _load_config()
    setup_logging(level=config.log_level, plugin_type=config.plugin_type)
    from core.tracing import configure_tracing

    configure_tracing(config)
    logger.info("Starting virtual-contributor engine with plugin: %s", config.plugin_type)
    # Resolve the plugin class up front so sizing is logged only where consumed.
    try:
        logged_plugin_class: type | None = PluginRegistry().discover(config.plugin_type)
    except Exception:  # discovery errors surface later in _run with full context
        logged_plugin_class = None
    _log_config(config, logged_plugin_class)

    # Expand default thread pool to prevent deadlocks when multiple
    # concurrent pipelines use asyncio.to_thread for sync LLM calls
    loop = asyncio.new_event_loop()
    loop.set_default_executor(concurrent.futures.ThreadPoolExecutor(max_workers=32))
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(_run(config))
    except KeyboardInterrupt:
        pass
    finally:
        # Crash-path flush: shutdown_on_exit=False removed the SDK atexit
        # hook (it unbounded process exit against a dead collector), so an
        # exception escaping _run would otherwise drop the last ~1s of
        # buffered spans — the very spans describing the crash. Same 5s
        # daemon-thread bound as the graceful path.
        try:
            loop.run_until_complete(_shutdown_tracing_bounded())
        except Exception:
            logger.warning("Crash-path tracing flush failed", exc_info=True)
        loop.close()


if __name__ == "__main__":
    main()
