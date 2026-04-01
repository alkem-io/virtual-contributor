"""Shared test fixtures: mock ports, sample event factories."""

from __future__ import annotations

from typing import AsyncIterator

import pytest

from core.events import (
    IngestBodyOfKnowledge,
    IngestWebsite,
    Input,
    Response,
)
from core.ports.knowledge_store import QueryResult


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
        for doc, meta, doc_id in zip(documents, metadatas, ids):
            self.collections[collection].append(
                {"document": doc, "metadata": meta, "id": doc_id}
            )

    async def delete_collection(self, collection: str) -> None:
        self.deleted.append(collection)
        self.collections.pop(collection, None)


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
    """Create a sample IngestWebsite event."""
    defaults = {
        "baseUrl": "https://example.com",
        "type": "website",
        "purpose": "knowledge",
        "personaId": "persona-789",
    }
    defaults.update(overrides)
    return IngestWebsite.model_validate(defaults)


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
