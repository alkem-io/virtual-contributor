from __future__ import annotations

import asyncio
import logging

import httpx

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
    ) -> None:
        self._api_key = api_key
        self._endpoint = endpoint.rstrip("/")
        self._model_name = model_name
        self._query_instruction = _resolve_query_instruction(
            model_name, query_instruction
        )
        if self._query_instruction:
            logger.info(
                "Embeddings adapter will wrap queries with instruction "
                "(model=%s, prefix_len=%d)",
                model_name,
                len(self._query_instruction),
            )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await self._call(texts)

    async def embed_query(self, texts: list[str]) -> list[list[float]]:
        if self._query_instruction:
            texts = [f"{self._query_instruction}{t}" for t in texts]
        return await self._call(texts)

    async def _call(self, texts: list[str]) -> list[list[float]]:
        last_exc = None
        async with httpx.AsyncClient(timeout=60.0) as client:
            for attempt in range(MAX_RETRIES):
                try:
                    response = await client.post(
                        f"{self._endpoint}/embeddings",
                        headers={
                            "Authorization": f"Bearer {self._api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": self._model_name,
                            "input": texts,
                        },
                    )
                    response.raise_for_status()
                    data = response.json()
                    return [item["embedding"] for item in data["data"]]
                except Exception as exc:
                    last_exc = exc
                    if attempt < MAX_RETRIES - 1:
                        delay = BASE_DELAY * (2 ** attempt)
                        logger.warning("Embeddings attempt %d failed, retrying: %s", attempt + 1, exc)
                        await asyncio.sleep(delay)
        raise last_exc
