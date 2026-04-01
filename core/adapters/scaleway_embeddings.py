from __future__ import annotations

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_DELAY = 1.0


class ScalewayEmbeddingsAdapter:
    """Scaleway embeddings adapter behind EmbeddingsPort."""

    def __init__(self, api_key: str, endpoint: str, model_name: str = "qwen3-embedding-8b") -> None:
        self._api_key = api_key
        self._endpoint = endpoint.rstrip("/")
        self._model_name = model_name

    async def embed(self, texts: list[str]) -> list[list[float]]:
        last_exc = None
        for attempt in range(MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
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
                    logger.warning("Scaleway embed attempt %d failed, retrying: %s", attempt + 1, exc)
                    await asyncio.sleep(delay)
        raise last_exc
