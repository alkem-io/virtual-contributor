"""Tests for the pipeline_timeout config field."""

from __future__ import annotations

import pytest
from core.config import BaseConfig


def _make_config(**overrides) -> BaseConfig:
    """Create a BaseConfig with minimal required fields."""
    defaults = {
        "llm_api_key": "test-key",
        "llm_provider": "openai",
        "plugin_type": "generic",
    }
    defaults.update(overrides)
    return BaseConfig(**defaults)


def test_pipeline_timeout_default():
    """Default pipeline_timeout is 3600 seconds."""
    config = _make_config()
    assert config.pipeline_timeout == 3600


def test_pipeline_timeout_custom():
    """Custom pipeline_timeout value is accepted."""
    config = _make_config(pipeline_timeout=7200)
    assert config.pipeline_timeout == 7200


def test_pipeline_timeout_invalid_zero():
    """pipeline_timeout=0 raises ValueError."""
    with pytest.raises(ValueError, match="PIPELINE_TIMEOUT must be greater than 0"):
        _make_config(pipeline_timeout=0)


def test_pipeline_timeout_invalid_negative():
    """Negative pipeline_timeout raises ValueError."""
    with pytest.raises(ValueError, match="PIPELINE_TIMEOUT must be greater than 0"):
        _make_config(pipeline_timeout=-1)
