"""Tests for application-level configuration wiring."""

from __future__ import annotations

import inspect
import logging

from core.config import BaseConfig
from main import _inject_answering_config, _log_config


class AnsweringSettingsPlugin:
    def __init__(
        self,
        *,
        answering_temperature: float | None = None,
        chain_of_thought_enabled: bool = True,
    ) -> None:
        self.answering_temperature = answering_temperature
        self.chain_of_thought_enabled = chain_of_thought_enabled


def test_answering_settings_are_injected_when_plugin_signature_declares_them() -> None:
    config = BaseConfig(
        llm_api_key="key",
        answering_llm_temperature=0.2,
        answering_chain_of_thought_enabled=False,
    )
    deps: dict[str, object] = {}

    _inject_answering_config(config, deps, inspect.signature(AnsweringSettingsPlugin))

    assert deps == {
        "answering_temperature": 0.2,
        "chain_of_thought_enabled": False,
    }


def test_answering_settings_are_in_startup_config_log(caplog) -> None:
    config = BaseConfig(
        llm_api_key="key",
        answering_llm_temperature=0.2,
        answering_chain_of_thought_enabled=False,
    )

    with caplog.at_level(logging.INFO):
        _log_config(config)

    assert "ANSWERING_LLM_TEMPERATURE=0.2" in caplog.text
    assert "ANSWERING_CHAIN_OF_THOUGHT_ENABLED=False" in caplog.text
