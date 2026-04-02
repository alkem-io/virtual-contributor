"""Provider factory — resolves LLM provider from config and returns a ready adapter."""

from __future__ import annotations

import logging
from typing import Any

from core.adapters.langchain_llm import LangChainLLMAdapter
from core.config import BaseConfig, LLMProvider

logger = logging.getLogger(__name__)

# Default model names per provider (FR-013)
DEFAULT_MODELS: dict[LLMProvider, str] = {
    LLMProvider.mistral: "mistral-large-latest",
    LLMProvider.openai: "gpt-4o",
    LLMProvider.anthropic: "claude-sonnet-4-6",
}


def _get_model_class(provider: LLMProvider) -> type:
    """Resolve the LangChain model class for a provider (lazy import)."""
    if provider == LLMProvider.mistral:
        from langchain_mistralai import ChatMistralAI
        return ChatMistralAI
    elif provider == LLMProvider.openai:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI
    elif provider == LLMProvider.anthropic:
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic
    raise ValueError(f"Unsupported provider: {provider}")


def create_llm_adapter(config: BaseConfig) -> LangChainLLMAdapter:
    """Create a LangChainLLMAdapter for the configured provider.

    Reads provider, model, API key, and generation parameters from config.
    Returns a ready-to-use adapter implementing LLMPort.
    """
    provider = config.llm_provider
    model_cls = _get_model_class(provider)
    model_name = config.llm_model or DEFAULT_MODELS[provider]

    kwargs: dict[str, Any] = {
        "model": model_name,
        "timeout": config.llm_timeout,
    }

    if config.llm_api_key:
        kwargs["api_key"] = config.llm_api_key
    if config.llm_base_url:
        kwargs["base_url"] = config.llm_base_url
    if config.llm_temperature is not None:
        kwargs["temperature"] = config.llm_temperature
    if config.llm_max_tokens is not None:
        kwargs["max_tokens"] = config.llm_max_tokens
    if config.llm_top_p is not None:
        kwargs["top_p"] = config.llm_top_p

    llm = model_cls(**kwargs)

    # Disable keep-alive to prevent stale connections to local LLM servers.
    # Must be done post-construction since ChatMistralAI serializes constructor kwargs.
    if config.llm_base_url:
        import httpx
        no_keepalive = httpx.Limits(max_keepalive_connections=0)
        if hasattr(llm, "async_client") and llm.async_client:
            llm.async_client = httpx.AsyncClient(
                base_url=config.llm_base_url,
                limits=no_keepalive,
                timeout=config.llm_timeout,
                headers=llm.async_client.headers,
            )

    return LangChainLLMAdapter(llm)
