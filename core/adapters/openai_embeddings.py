from __future__ import annotations

import asyncio
import logging

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_DELAY = 1.0


class OpenAIEmbeddingsAdapter:
    """OpenAI embeddings adapter behind EmbeddingsPort.

    OpenAI's text-embedding-3-* models are not instruction-aware, so
    :meth:`embed_query` delegates to :meth:`embed` without wrapping.
    """

    def __init__(self, api_key: str, model_name: str = "text-embedding-3-small") -> None:
        self._client = AsyncOpenAI(api_key=api_key)
        self._model_name = model_name

    async def embed(self, texts: list[str]) -> list[list[float]]:
        last_exc = None
        for attempt in range(MAX_RETRIES):
            try:
                response = await self._client.embeddings.create(
                    model=self._model_name,
                    input=texts,
                )
                return [item.embedding for item in response.data]
            except Exception as exc:
                last_exc = exc
                if attempt < MAX_RETRIES - 1:
                    delay = BASE_DELAY * (2 ** attempt)
                    logger.warning("OpenAI embed attempt %d failed, retrying: %s", attempt + 1, exc)
                    await asyncio.sleep(delay)
        raise last_exc

    async def embed_query(self, texts: list[str]) -> list[list[float]]:
        return await self.embed(texts)
