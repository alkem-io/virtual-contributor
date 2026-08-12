"""Startup logging tracing regression coverage."""

from core.config import BaseConfig
from main import _log_config


def test_tracing_config_logging_is_safe(caplog) -> None:
    _log_config(BaseConfig(llm_base_url="http://local", tracing_otlp_headers="Authorization=secret"))
    assert "Authorization=secret" not in caplog.text
