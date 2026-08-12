"""Fail-open LangChain callback instrumentation for provider calls."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from opentelemetry import trace
from opentelemetry.trace import SpanKind

from core.config import BaseConfig
from core.tracing import get_tracer, set_content_attribute

logger = logging.getLogger(__name__)


class VCTracingCallbackHandler(BaseCallbackHandler):
    """Emit one client span for each LangChain chat model run."""

    raise_error = False

    def __init__(self, config: BaseConfig) -> None:
        super().__init__()
        self._config = config
        self._spans: dict[str, Any] = {}

    @staticmethod
    def _key(run_id: object) -> str:
        return str(run_id)

    @staticmethod
    def _model_name(serialized: dict[str, Any] | None, kwargs: dict[str, Any]) -> str:
        serialized = serialized or {}
        return str(
            kwargs.get("invocation_params", {}).get("model")
            or kwargs.get("model_name")
            or serialized.get("name")
            or serialized.get("id", ["chat"])[-1]
        )

    @staticmethod
    def _messages_text(messages: Any) -> str:
        try:
            groups = messages if isinstance(messages, list) else [messages]
            text: list[str] = []
            for group in groups:
                for message in group if isinstance(group, list) else [group]:
                    text.append(str(getattr(message, "content", message)))
            return "\n".join(text)
        except Exception:
            return ""

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: object,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Open the provider-attempt span keyed by LangChain's run ID."""
        try:
            model = self._model_name(serialized, kwargs)
            span = get_tracer().start_span(f"chat {model}", kind=SpanKind.CLIENT)
            span.set_attribute("gen_ai.operation.name", "chat")
            span.set_attribute("gen_ai.request.model", model)
            set_content_attribute(span, "gen_ai.prompt", self._messages_text(messages), self._config)
            graph_node = (metadata or {}).get("langgraph_node")
            if graph_node is not None:
                span.set_attribute("vc.graph_node", str(graph_node))
            self._spans[self._key(run_id)] = span
        except Exception:
            logger.warning("Tracing callback failed on chat start", exc_info=True)

    def on_llm_end(self, response: Any, *, run_id: object, **kwargs: Any) -> None:
        """Attach provider usage metadata, then complete the attempt span."""
        try:
            span = self._spans.pop(self._key(run_id), None)
            if span is None:
                return
            try:
                generation = response.generations[0][0]
                message = getattr(generation, "message", None)
                usage = getattr(message, "usage_metadata", None)
                completion = getattr(message, "content", None)
            except (AttributeError, IndexError, TypeError):
                usage = None
                completion = None
            llm_output = getattr(response, "llm_output", None) or {}
            usage = usage or llm_output.get("token_usage")
            if isinstance(usage, dict):
                for source, target in (
                    ("input_tokens", "gen_ai.usage.input_tokens"),
                    ("prompt_tokens", "gen_ai.usage.input_tokens"),
                    ("output_tokens", "gen_ai.usage.output_tokens"),
                    ("completion_tokens", "gen_ai.usage.output_tokens"),
                ):
                    if source in usage and usage[source] is not None:
                        span.set_attribute(target, int(usage[source]))
            model = llm_output.get("model_name") or llm_output.get("model")
            if model:
                span.set_attribute("gen_ai.response.model", str(model))
            set_content_attribute(span, "gen_ai.completion", completion, self._config)
            span.end()
        except Exception:
            logger.warning("Tracing callback failed on LLM end", exc_info=True)

    def on_llm_error(self, error: BaseException, *, run_id: object, **kwargs: Any) -> None:
        """Mark and close a failed provider attempt without leaking errors."""
        try:
            span = self._spans.pop(self._key(run_id), None)
            if span is None:
                return
            span.record_exception(error)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(error)))
            span.end()
        except Exception:
            logger.warning("Tracing callback failed on LLM error", exc_info=True)
