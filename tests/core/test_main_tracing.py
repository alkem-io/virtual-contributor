"""Main composition seams and startup logging tracing regression coverage."""

from unittest.mock import MagicMock, patch

from core.config import BaseConfig
from core.tracing import configure_tracing, reset_tracing_for_tests
from main import _log_config, _mask_sensitive, _shutdown_tracing_bounded


def test_tracing_config_logging_is_safe(caplog) -> None:
    _log_config(BaseConfig(llm_base_url="http://local", tracing_otlp_headers="Authorization=secret"))
    assert "Authorization=secret" not in caplog.text


def test_url_userinfo_is_masked() -> None:
    assert _mask_sensitive("llm_base_url", "https://user:secret@llm.internal/v1") == "https://***@llm.internal/v1"
    assert _mask_sensitive("tracing_otlp_endpoint", "https://token@collector.internal/v1/traces") == "https://***@collector.internal/v1/traces"


def test_factory_adds_callbacks_only_after_local_tracing_is_configured() -> None:
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from core.provider_factory import create_llm_adapter

    config = BaseConfig(
        llm_base_url="http://local",
        tracing_enabled=True,
        tracing_otlp_endpoint="http://collector.internal/v1/traces",
    )
    model = MagicMock()
    with patch("core.provider_factory._get_model_class", return_value=MagicMock(return_value=model)) as factory:
        reset_tracing_for_tests()
        create_llm_adapter(config)
        assert "callbacks" not in factory.return_value.call_args.kwargs
        configure_tracing(config, span_exporter=InMemorySpanExporter())
        create_llm_adapter(config)
        assert len(factory.return_value.call_args.kwargs["callbacks"]) == 1
    reset_tracing_for_tests()


async def test_bounded_shutdown_does_not_block_following_cleanup(monkeypatch) -> None:
    import main

    seen: dict[str, float] = {}

    async def bounded(coro, *, timeout: float):
        seen["timeout"] = timeout
        coro.close()
        raise TimeoutError

    monkeypatch.setattr(main.asyncio, "wait_for", bounded)
    await _shutdown_tracing_bounded()
    assert seen["timeout"] == 5
    # The coroutine returned, so callers can immediately continue to close the
    # transport even when the exporter worker is blackholed.
    assert main._shutdown_tracing_bounded is _shutdown_tracing_bounded
