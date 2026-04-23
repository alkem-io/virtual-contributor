from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingsPort(Protocol):
    """Port for text embedding generation."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for documents (indexing side).

        Callers should use this for texts that will be stored/indexed.
        """
        ...

    async def embed_query(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for retrieval queries.

        Semantically distinct from :meth:`embed`: instruction-aware embedding
        models (e.g. Qwen3-Embedding) require a task-specific prefix on the
        query side for retrieval to rank correctly. Adapters that target
        plain embedding models may implement this as an alias for
        :meth:`embed`.
        """
        ...
