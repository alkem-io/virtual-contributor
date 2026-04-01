"""Space / body-of-knowledge ingestion event models."""

from __future__ import annotations

import time

from pydantic import Field

from core.events.base import EventBase


class ErrorDetail(EventBase):
    """Structured error information for ingestion failures."""

    code: str | None = None
    message: str | None = None


class IngestBodyOfKnowledge(EventBase):
    """Request to ingest a body of knowledge (space)."""

    body_of_knowledge_id: str = Field(alias="bodyOfKnowledgeId")
    type: str
    purpose: str
    persona_id: str = Field(alias="personaId")


class IngestBodyOfKnowledgeResult(EventBase):
    """Result of a body-of-knowledge ingestion run."""

    body_of_knowledge_id: str = Field(alias="bodyOfKnowledgeId")
    type: str
    purpose: str
    persona_id: str = Field(alias="personaId")
    timestamp: int = Field(
        default_factory=lambda: int(time.time() * 1000)
    )
    result: str = "success"
    error: ErrorDetail | None = None
