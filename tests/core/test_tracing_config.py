"""Configuration coverage for the optional tracing subsystem."""

import pytest

from core.config import BaseConfig
from main import _mask_sensitive


def _config(**values) -> BaseConfig:
    return BaseConfig(llm_base_url="http://local-model", **values)


def test_tracing_defaults_are_dark() -> None:
    config = _config()
    assert config.tracing_enabled is False
    assert config.tracing_otlp_endpoint is None
    assert config.tracing_sample_ratio == 1.0


def test_tracing_config_binds_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRACING_ENABLED", "true")
    monkeypatch.setenv("TRACING_OTLP_ENDPOINT", "http://internal/traces")
    monkeypatch.setenv("TRACING_SAMPLE_RATIO", "0.25")
    config = _config()
    assert config.tracing_enabled is True
    assert config.tracing_otlp_endpoint == "http://internal/traces"
    assert config.tracing_sample_ratio == 0.25


@pytest.mark.parametrize("key,value", [("tracing_sample_ratio", 1.1), ("tracing_content_max_chars", 0)])
def test_invalid_tracing_config_is_rejected(key: str, value: float | int) -> None:
    with pytest.raises(ValueError):
        _config(**{key: value})


def test_otlp_headers_are_masked() -> None:
    assert _mask_sensitive("tracing_otlp_headers", "secret-value").startswith("sec")
    assert "secret-value" not in _mask_sensitive("tracing_otlp_headers", "secret-value")
