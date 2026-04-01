"""Response event models – outbound query result payload."""

from __future__ import annotations

from pydantic import Field

from core.events.base import EventBase


class Source(EventBase):
    """A single knowledge-base source reference attached to a response."""

    chunk_index: int | None = Field(default=None, alias="chunkIndex")
    embedding_type: str | None = Field(default=None, alias="embeddingType")
    document_id: str | None = Field(default=None, alias="documentId")
    source: str | None = None
    title: str | None = None
    type: str | None = None
    score: float | None = None
    uri: str | None = None


class Response(EventBase):
    """Query result payload returned to the platform."""

    result: str | None = Field(default=None, alias="result")
    human_language: str | None = Field(default=None, alias="humanLanguage")
    result_language: str | None = Field(default=None, alias="resultLanguage")
    knowledge_language: str | None = Field(
        default=None, alias="knowledgeLanguage"
    )
    original_result: str | None = Field(
        default=None, alias="originalResult"
    )
    sources: list[Source] = Field(default_factory=list)
    thread_id: str | None = Field(default=None, alias="threadId")
