from __future__ import annotations

import asyncio
import logging

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI

from core.ports.embeddings import (
    EmbeddingInputError, EmbeddingPermanentError, EmbeddingTransientError,
)

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_DELAY = 1.0


class OpenAIEmbeddingsAdapter:
    """OpenAI embeddings adapter behind EmbeddingsPort.

    OpenAI's text-embedding-3-* models are not instruction-aware, so
    :meth:`embed_query` delegates to :meth:`embed` without wrapping.
    """

    def __init__(self, api_key: str, model_name: str = "text-embedding-3-small", query_max_utf8_bytes: int = 32768, max_attempts: int = 3, attempt_timeout_seconds: float = 20, total_deadline_seconds: float = 45) -> None:
        # Document embedding intentionally keeps the historical SDK client and
        # retry behaviour.  Query embedding has an adapter-owned retry budget,
        # so it must use a separate zero-retry SDK view: otherwise one logical
        # outer attempt can issue the SDK's hidden retry ladder.
        self._client = AsyncOpenAI(api_key=api_key)
        self._query_client = self._client.with_options(max_retries=0)
        self._model_name = model_name
        self._query_max_utf8_bytes = query_max_utf8_bytes
        self._max_attempts = max_attempts
        self._attempt_timeout_seconds = attempt_timeout_seconds
        self._total_deadline_seconds = total_deadline_seconds

    async def embed(self, texts: list[str]) -> list[list[float]]:
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                response = await self._client.embeddings.create(
                    model=self._model_name, input=texts,
                )
                return [item.embedding for item in response.data]
            except Exception as exc:
                last_exc = exc
                if attempt + 1 < MAX_RETRIES:
                    await asyncio.sleep(BASE_DELAY * (2 ** attempt))
        assert last_exc is not None
        raise last_exc

    async def embed_query(self, texts: list[str]) -> list[list[float]]:
        if any(len(text.encode("utf-8")) > self._query_max_utf8_bytes for text in texts):
            raise EmbeddingInputError("query exceeds configured UTF-8 input limit")
        return await self._call(texts)

    @staticmethod
    def _transient(exc: Exception) -> bool:
        status = getattr(exc, "status_code", None)
        return isinstance(
            exc,
            (TimeoutError, ConnectionError, APIConnectionError, APITimeoutError),
        ) or status in {408, 429} or (isinstance(status, int) and status >= 500)

    async def _call(self, texts: list[str]) -> list[list[float]]:
        last_exc: Exception | None = None
        try:
            async with asyncio.timeout(self._total_deadline_seconds):
                for attempt in range(self._max_attempts):
                    try:
                        response = await asyncio.wait_for(
                            self._query_client.embeddings.create(
                                model=self._model_name, input=texts,
                            ),
                            timeout=self._attempt_timeout_seconds,
                        )
                        return [item.embedding for item in response.data]
                    except Exception as exc:
                        last_exc = exc
                        if not self._transient(exc):
                            raise EmbeddingPermanentError("embedding provider rejected request") from exc
                        if attempt + 1 < self._max_attempts:
                            logger.warning("OpenAI embedding attempt %d failed; error_type=%s", attempt + 1, type(exc).__name__)
                            await asyncio.sleep(BASE_DELAY * (2 ** attempt))
        except TimeoutError as exc:
            raise EmbeddingTransientError("embedding deadline exhausted") from exc
        raise EmbeddingTransientError("embedding attempts exhausted") from last_exc
