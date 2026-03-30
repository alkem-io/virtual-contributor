from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingsPort(Protocol):
    """Port for text embedding generation."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a batch of texts."""
        ...
