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

    # Construct plugin with dependencies
    deps = container.resolve_for_plugin(plugin_class)
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

    try:
        asyncio.run(_run(config))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
