"""Application entry point — bootstrap, wire, run."""

from __future__ import annotations

import asyncio
import json
import logging
import signal

from core.config import BaseConfig
from core.container import Container
from core.health import HealthServer
from core.logging import setup_logging
from core.ports.llm import LLMPort
from core.ports.embeddings import EmbeddingsPort
from core.ports.knowledge_store import KnowledgeStorePort
from core.registry import PluginRegistry
from core.router import Router

logger = logging.getLogger(__name__)


def _mask_sensitive(name: str, value) -> str:
    """Mask API key values for logging."""
    if value is None:
        return "None"
    s = str(value)
    if "api_key" in name:
        return s[:3] + "****" if len(s) > 3 else "****"
    return s


def _log_config(config: BaseConfig) -> None:
    """Log all configurable summarization/retrieval fields at startup."""
    fields = [
        "summarize_llm_provider",
        "summarize_llm_model",
        "summarize_llm_api_key",
        "summarize_llm_base_url",
        "summarize_llm_temperature",
        "summarize_llm_timeout",
        "bok_llm_provider",
        "bok_llm_model",
        "bok_llm_api_key",
        "bok_llm_base_url",
        "expert_n_results",
        "expert_min_score",
        "guidance_n_results",
        "guidance_min_score",
        "max_context_chars",
        "summary_chunk_threshold",
    ]
    for name in fields:
        value = getattr(config, name, None)
        logger.info("Config: %s=%s", name.upper(), _mask_sensitive(name, value))


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


def _create_adapters(config: BaseConfig, container: Container) -> None:
    """Wire adapter instances into the container based on config."""
    # LLM adapter — unified provider factory with per-plugin override support
    from core.provider_factory import create_llm_adapter

    effective_config = _resolve_plugin_llm_config(config)
    llm_adapter = create_llm_adapter(effective_config)
    container.register(LLMPort, llm_adapter)
    logger.info(
        "LLM provider: %s | model: %s | base_url: %s",
        effective_config.llm_provider.value,
        effective_config.llm_model or "default",
        effective_config.llm_base_url or "default",
    )

    # Embeddings adapters
    if config.embeddings_api_key and config.embeddings_endpoint:
        from core.adapters.openai_compatible_embeddings import OpenAICompatibleEmbeddingsAdapter

        container.register(
            EmbeddingsPort,
            OpenAICompatibleEmbeddingsAdapter(
                api_key=config.embeddings_api_key,
                endpoint=config.embeddings_endpoint,
                model_name=config.embeddings_model_name or "qwen3-embedding-8b",
            ),
        )

    # Knowledge store
    if config.vector_db_host:
        from core.adapters.chromadb import ChromaDBAdapter

        embeddings_adapter = container._bindings.get(EmbeddingsPort)
        container.register(
            KnowledgeStorePort,
            ChromaDBAdapter(
                host=config.vector_db_host,
                port=config.vector_db_port,
                credentials=config.vector_db_credentials,
                embeddings=embeddings_adapter,
            ),
        )

    # OpenAI Assistants (always available — per-request API keys)
    from core.adapters.openai_assistant import OpenAIAssistantAdapter

    container.register(OpenAIAssistantAdapter, OpenAIAssistantAdapter())


async def _run(config: BaseConfig) -> None:
    """Main async entrypoint."""
    from core.adapters.rabbitmq import RabbitMQAdapter

    # Discover plugin
    registry = PluginRegistry()
    plugin_class = registry.discover(config.plugin_type)
    logger.info("Discovered plugin: %s", plugin_class.name)

    # Wire adapters
    container = Container()
    _create_adapters(config, container)

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
            "Summarization LLM configured: provider=%s, model=%s, base_url=%s",
            config.summarize_llm_provider.value,
            config.summarize_llm_model,
            config.summarize_llm_base_url or "(inherited from main LLM)",
        )

    # Create BoK LLM adapter if fully configured (needs large context window)
    bok_llm = None
    bok_fields = [
        config.bok_llm_provider,
        config.bok_llm_model,
        config.bok_llm_api_key,
    ]
    if all(f is not None for f in bok_fields):
        from core.provider_factory import create_llm_adapter as _create_bok

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
        bok_llm = _create_bok(BaseConfig(**synth_data), disable_thinking=True)
        logger.info(
            "BoK LLM configured: provider=%s, model=%s, base_url=%s",
            config.bok_llm_provider.value,
            config.bok_llm_model,
            config.bok_llm_base_url or "(inherited from main LLM)",
        )

    # Construct plugin with dependencies
    deps = container.resolve_for_plugin(plugin_class)
    # Inject per-plugin retrieval config
    import inspect
    sig = inspect.signature(plugin_class.__init__)
    plugin_name = config.plugin_type.lower().replace("-", "_") if config.plugin_type else ""
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
    # Inject summarization LLM for ingest plugins
    if "summarize_llm" in sig.parameters:
        deps["summarize_llm"] = summarize_llm
    # Inject BoK LLM for ingest plugins (large-context model for BoK summary)
    if "bok_llm" in sig.parameters:
        deps["bok_llm"] = bok_llm
    # Inject chunk threshold for ingest plugins
    if "chunk_threshold" in sig.parameters:
        deps["chunk_threshold"] = config.summary_chunk_threshold
    plugin = plugin_class(**deps)

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

    # Message handler
    async def on_message(body: dict) -> None:
        event = None
        try:
            event = router.parse_event(body)
            response = await plugin.handle(event)
            envelope = router.build_response_envelope(response, event)
            await transport.publish(
                config.rabbitmq_exchange,
                config.rabbitmq_result_routing_key,
                json.dumps(envelope).encode("utf-8"),
            )
        except Exception as exc:
            logger.exception("Error handling message: %s", exc)
            from core.events.response import Response

            error_response = Response(result=f"Error: {exc}")
            envelope = router.build_response_envelope(error_response, event) if event else {"response": error_response.model_dump()}
            await transport.publish(
                config.rabbitmq_exchange,
                config.rabbitmq_result_routing_key,
                json.dumps(envelope).encode("utf-8"),
            )

    # Start consuming
    await transport.consume(config.rabbitmq_input_queue, on_message)

    # Health server
    health = HealthServer(port=config.health_port)
    health.add_check("rabbitmq", transport.is_connected)
    health.add_check("plugin", lambda: True)
    await health.start()

    logger.info("Engine ready — consuming from %s", config.rabbitmq_input_queue)

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
    await health.stop()
    await plugin.shutdown()
    await transport.close()
    logger.info("Shutdown complete")


def main() -> None:
    config = BaseConfig()
    setup_logging(level=config.log_level, plugin_type=config.plugin_type)
    logger.info("Starting virtual-contributor engine with plugin: %s", config.plugin_type)
    _log_config(config)

    try:
        asyncio.run(_run(config))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
