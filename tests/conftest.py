"""Shared test fixtures: mock ports, sample event factories."""

from __future__ import annotations

from typing import AsyncIterator

import pytest

from core.events import (
    IngestBodyOfKnowledge,
    IngestWebsite,
    Input,
    Response,
    WebsiteSource,
)
from core.ports.knowledge_store import GetResult, QueryResult


# ---------------------------------------------------------------------------
# Mock port implementations
# ---------------------------------------------------------------------------


class MockLLMPort:
    """Mock LLM adapter for testing."""

    def __init__(self, response: str = "Mock LLM response") -> None:
        self.response = response
        self.calls: list[list[dict]] = []

    async def invoke(self, messages: list[dict]) -> str:
        self.calls.append(messages)
        return self.response

    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        self.calls.append(messages)
        for word in self.response.split():
            yield word


class MockEmbeddingsPort:
    """Mock embeddings adapter for testing."""

    def __init__(self, dimension: int = 384) -> None:
        self.dimension = dimension
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [[0.1] * self.dimension for _ in texts]


class MockKnowledgeStorePort:
    """Mock knowledge store adapter for testing."""

    def __init__(self) -> None:
        self.collections: dict[str, list[dict]] = {}
        self.query_calls: list[tuple] = []
        self.deleted: list[str] = []

    async def query(
        self,
        collection: str,
        query_texts: list[str],
        n_results: int = 10,
    ) -> QueryResult:
        self.query_calls.append((collection, query_texts, n_results))
        return QueryResult(
            documents=[["doc1", "doc2"]],
            metadatas=[[{"source": "test"}, {"source": "test"}]],
            distances=[[0.1, 0.2]],
            ids=[["id1", "id2"]],
        )

    async def ingest(
        self,
        collection: str,
        documents: list[str],
        metadatas: list[dict],
        ids: list[str],
        embeddings: list[list[float]] | None = None,
    ) -> None:
        self.collections.setdefault(collection, [])
        for i, (doc, meta, doc_id) in enumerate(zip(documents, metadatas, ids)):
            entry: dict = {"document": doc, "metadata": meta, "id": doc_id}
            if embeddings is not None:
                entry["embedding"] = embeddings[i]
            # Upsert: replace existing entry with same ID
            self.collections[collection] = [
                it for it in self.collections[collection] if it["id"] != doc_id
            ]
            self.collections[collection].append(entry)

    async def delete_collection(self, collection: str) -> None:
        self.deleted.append(collection)
        self.collections.pop(collection, None)

    async def get(
        self,
        collection: str,
        ids: list[str] | None = None,
        where: dict | None = None,
        include: list[str] | None = None,
    ) -> GetResult:
        items = self.collections.get(collection, [])
        matched = items
        if ids is not None:
            matched = [it for it in matched if it["id"] in ids]
        if where is not None:
            for key, value in where.items():
                matched = [
                    it for it in matched
                    if it.get("metadata", {}).get(key) == value
                ]
        result_ids = [it["id"] for it in matched]
        result_metadatas = (
            [it.get("metadata", {}) for it in matched]
            if include and "metadatas" in include
            else None
        )
        result_documents = (
            [it.get("document", "") for it in matched]
            if include and "documents" in include
            else None
        )
        result_embeddings = (
            [it.get("embedding", []) for it in matched]
            if include and "embeddings" in include
            else None
        )
        return GetResult(
            ids=result_ids,
            metadatas=result_metadatas,
            documents=result_documents,
            embeddings=result_embeddings,
        )

    async def delete(
        self,
        collection: str,
        ids: list[str] | None = None,
        where: dict | None = None,
    ) -> None:
        items = self.collections.get(collection, [])
        if not items:
            return
        to_remove = set()
        for i, it in enumerate(items):
            if ids is not None and it["id"] in ids:
                to_remove.add(i)
            if where is not None:
                match = all(
                    it.get("metadata", {}).get(k) == v
                    for k, v in where.items()
                )
                if match:
                    to_remove.add(i)
        self.collections[collection] = [
            it for i, it in enumerate(items) if i not in to_remove
        ]


class MockTransportPort:
    """Mock transport adapter for testing."""

    def __init__(self) -> None:
        self.published: list[tuple[str, str, bytes]] = []
        self.consuming: dict[str, bool] = {}
        self.closed = False

    async def consume(self, queue: str, callback) -> None:
        self.consuming[queue] = True

    async def publish(self, exchange: str, routing_key: str, message: bytes) -> None:
        self.published.append((exchange, routing_key, message))

    async def close(self) -> None:
        self.closed = True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_llm():
    return MockLLMPort()


@pytest.fixture
def mock_embeddings():
    return MockEmbeddingsPort()


@pytest.fixture
def mock_knowledge_store():
    return MockKnowledgeStorePort()


@pytest.fixture
def mock_transport():
    return MockTransportPort()


# ---------------------------------------------------------------------------
# Event factories
# ---------------------------------------------------------------------------


def make_input(**overrides) -> Input:
    """Create a sample Input event with sensible defaults."""
    defaults = {
        "engine": "generic-openai",
        "userID": "user-123",
        "message": "What is Alkemio?",
        "personaID": "persona-456",
        "displayName": "Test VC",
        "resultHandler": {
            "action": "postReply",
            "roomDetails": {
                "roomID": "room-1",
                "actorID": "actor-1",
                "threadID": "thread-1",
                "vcInteractionID": "vc-int-1",
            },
        },
    }
    defaults.update(overrides)
    return Input.model_validate(defaults)


def make_response(**overrides) -> Response:
    """Create a sample Response event."""
    defaults = {"result": "Test response", "sources": []}
    defaults.update(overrides)
    return Response.model_validate(defaults)


def make_ingest_website(**overrides) -> IngestWebsite:
    """Create a sample IngestWebsite event.

    Supports both legacy format (baseUrl) and new format (sources list).
    """
    defaults: dict = {
        "baseUrl": "https://example.com",
        "type": "website",
        "purpose": "knowledge",
        "personaId": "persona-789",
    }
    defaults.update(overrides)
    return IngestWebsite.model_validate(defaults)


def make_website_source(**overrides) -> WebsiteSource:
    """Create a sample WebsiteSource for testing."""
    defaults: dict = {
        "url": "https://example.com",
    }
    defaults.update(overrides)
    return WebsiteSource.model_validate(defaults)


def make_ingest_body_of_knowledge(**overrides) -> IngestBodyOfKnowledge:
    """Create a sample IngestBodyOfKnowledge event."""
    defaults = {
        "bodyOfKnowledgeId": "bok-123",
        "type": "alkemio-space",
        "purpose": "knowledge",
        "personaId": "persona-789",
    }
    defaults.update(overrides)
    return IngestBodyOfKnowledge.model_validate(defaults)
