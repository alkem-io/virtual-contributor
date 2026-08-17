from __future__ import annotations

import asyncio
import json
import logging

import httpx

from core.ports.embeddings import (
    EmbeddingInputError, EmbeddingPermanentError, EmbeddingTransientError,
)

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_DELAY = 1.0

QWEN3_RETRIEVAL_INSTRUCTION = (
    "Instruct: Given a web search query, retrieve relevant passages that "
    "answer the query\nQuery: "
)


def _resolve_query_instruction(
    model_name: str, explicit: str | None
) -> str:
    """Resolve the query-side instruction prefix.

    - If *explicit* is provided (including empty string), use it verbatim.
    - Else auto-apply the Qwen3 retrieval prompt for any
      ``qwen3-embedding*`` model.
    - Else no prefix.
    """
    if explicit is not None:
        return explicit
    if model_name.lower().startswith("qwen3-embedding"):
        return QWEN3_RETRIEVAL_INSTRUCTION
    return ""


class OpenAICompatibleEmbeddingsAdapter:
    """OpenAI-compatible embeddings adapter behind EmbeddingsPort.

    Works with any provider exposing the ``/embeddings`` endpoint in the
    OpenAI format (Scaleway, Together AI, vLLM, Ollama, etc.).

    Instruction-aware query prefix:
        Qwen3-Embedding and similar instruction-aware models rank queries
        much better when wrapped with a task prompt. :meth:`embed_query`
        prepends the configured prefix to each input. :meth:`embed` never
        wraps — documents stay in the plain embedding space.
    """

    def __init__(
        self,
        api_key: str,
        endpoint: str,
        model_name: str,
        query_instruction: str | None = None,
        query_max_utf8_bytes: int = 32768,
        max_attempts: int = 3,
        attempt_timeout_seconds: float = 20,
        total_deadline_seconds: float = 45,
    ) -> None:
        self._api_key = api_key
        self._endpoint = endpoint.rstrip("/")
        self._model_name = model_name
        self._query_instruction = _resolve_query_instruction(
            model_name, query_instruction
        )
        self._query_max_utf8_bytes = query_max_utf8_bytes
        self._max_attempts = max_attempts
        self._attempt_timeout_seconds = attempt_timeout_seconds
        self._total_deadline_seconds = total_deadline_seconds
        if self._query_instruction:
            logger.info(
                "Embeddings adapter will wrap queries with instruction "
                "(model=%s, prefix_len=%d)",
                model_name,
                len(self._query_instruction),
            )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # Ingestion deliberately retains the repository's frozen document
        # policy: retry any exception and re-raise the original on exhaustion.
        last_exc: Exception | None = None
        # This is the frozen ingestion-side client contract from develop.
        # Query deadlines intentionally do not alter document ingestion.
        async with httpx.AsyncClient(timeout=60.0) as client:
            for attempt in range(MAX_RETRIES):
                try:
                    response = await client.post(
                        f"{self._endpoint}/embeddings",
                        headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                        json={"model": self._model_name, "input": texts},
                    )
                    response.raise_for_status()
                    data = response.json()
                    return [item["embedding"] for item in data["data"]]
                except Exception as exc:
                    last_exc = exc
                    if attempt + 1 < MAX_RETRIES:
                        await asyncio.sleep(BASE_DELAY * (2 ** attempt))
        assert last_exc is not None
        raise last_exc

    async def embed_query(self, texts: list[str]) -> list[list[float]]:
        if self._query_instruction:
            texts = [f"{self._query_instruction}{t}" for t in texts]
        self._validate_query_inputs(texts)
        return await self._call(texts, is_query=True)

    def _validate_query_inputs(self, texts: list[str]) -> None:
        if any(len(text.encode("utf-8")) > self._query_max_utf8_bytes for text in texts):
            raise EmbeddingInputError("query exceeds configured UTF-8 input limit")

    @staticmethod
    def _transient(exc: Exception) -> bool:
        # RemoteProtocolError (mid-stream disconnect) and ProxyError sit
        # under httpx.TransportError but outside NetworkError/TimeoutException,
        # so they need an explicit allow -- a dropped connection or a flaky
        # proxy is exactly as transient as a connect timeout. JSONDecodeError
        # means a truncated/non-JSON body on an otherwise-successful response
        # (mirrors the store adapter's own retry rule for the same error).
        if isinstance(exc, (
            TimeoutError, httpx.TimeoutException, httpx.ConnectError,
            httpx.NetworkError, httpx.RemoteProtocolError, httpx.ProxyError,
            json.JSONDecodeError,
        )):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code == 408 or exc.response.status_code == 429 or exc.response.status_code >= 500
        return False

    async def _call(self, texts: list[str], *, is_query: bool = False) -> list[list[float]]:
        last_exc: Exception | None = None
        try:
            async with asyncio.timeout(self._total_deadline_seconds):
                async with httpx.AsyncClient(timeout=self._attempt_timeout_seconds) as client:
                    for attempt in range(self._max_attempts):
                        try:
                            response = await asyncio.wait_for(client.post(
                                f"{self._endpoint}/embeddings",
                                headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                                json={"model": self._model_name, "input": texts},
                            ), timeout=self._attempt_timeout_seconds)
                            response.raise_for_status()
                            data = response.json()
                            return [item["embedding"] for item in data["data"]]
                        except Exception as exc:
                            last_exc = exc
                            if not self._transient(exc):
                                raise EmbeddingPermanentError("embedding provider rejected request") from exc
                            if attempt + 1 < self._max_attempts:
                                logger.warning("Embeddings attempt %d failed; error_type=%s", attempt + 1, type(exc).__name__)
                                await asyncio.sleep(BASE_DELAY * (2 ** attempt))
        except TimeoutError as exc:
            raise EmbeddingTransientError("embedding deadline exhausted") from exc
        if last_exc is not None:
            raise EmbeddingTransientError("embedding attempts exhausted") from last_exc
        raise EmbeddingPermanentError("embedding call did not complete")
