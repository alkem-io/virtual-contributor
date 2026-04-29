"""Website ingestion event models."""

from __future__ import annotations

import time
from enum import Enum

from pydantic import Field

from core.events.base import EventBase


class IngestionResult(str, Enum):
    """Outcome of a website ingestion run."""

    SUCCESS = "success"
    FAILURE = "failure"


class IngestWebsite(EventBase):
    """Request to crawl and ingest a website into the knowledge base."""

    base_url: str = Field(alias="baseUrl")
    type: str
    purpose: str
    persona_id: str = Field(alias="personaId")
    summarization_model: str = Field(
        default="mistral-medium", alias="summarizationModel"
    )


class IngestWebsiteResult(EventBase):
    """Result of a website ingestion run.

    Carries the identification fields (``bodyOfKnowledgeId``, ``type``,
    ``purpose``, ``personaId``) so the alkemio-server result handler can
    correlate the result back to the persona that owns the body of
    knowledge. ``bodyOfKnowledgeId`` defaults to an empty string because
    website-typed bodies of knowledge are URL-identified, not UUID-keyed.
    """

    body_of_knowledge_id: str = Field(default="", alias="bodyOfKnowledgeId")
    type: str = ""
    purpose: str = ""
    persona_id: str = Field(default="", alias="personaId")
    timestamp: int = Field(
        default_factory=lambda: int(time.time() * 1000)
    )
    result: IngestionResult = IngestionResult.SUCCESS
    error: str = ""
