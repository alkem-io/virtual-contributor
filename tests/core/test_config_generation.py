"""Tests for the opt-in retrieval-answering generation settings."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.config import BaseConfig
from core.provider_factory import create_llm_adapter


@patch("langchain_openai.ChatOpenAI")
def test_answering_temperature_is_unset_and_does_not_change_adapter_kwargs(
    mock_model: MagicMock,
) -> None:
    mock_model.return_value = MagicMock()
    config = BaseConfig(llm_provider="openai", llm_api_key="key")

    create_llm_adapter(config)

    assert config.answering_llm_temperature is None
    assert mock_model.call_args.kwargs == {
        "model": "gpt-4o",
        "timeout": 120,
        "max_retries": 0,
        "api_key": "key",
    }


@pytest.mark.parametrize("temperature", [-0.1, 2.1])
def test_answering_temperature_rejects_out_of_range_values(temperature: float) -> None:
    with pytest.raises(ValueError, match="ANSWERING_LLM_TEMPERATURE.*0.0 and 2.0"):
        BaseConfig(llm_api_key="key", answering_llm_temperature=temperature)


@pytest.mark.parametrize("temperature", [0.0, 0.3, 2.0])
def test_answering_temperature_accepts_in_range_values(temperature: float) -> None:
    config = BaseConfig(llm_api_key="key", answering_llm_temperature=temperature)

    assert config.answering_llm_temperature == temperature


def test_chain_of_thought_flag_defaults_enabled_and_can_be_disabled() -> None:
    assert BaseConfig(llm_api_key="key").answering_chain_of_thought_enabled is True
    assert (
        BaseConfig(
            llm_api_key="key", answering_chain_of_thought_enabled=False
        ).answering_chain_of_thought_enabled
        is False
    )
