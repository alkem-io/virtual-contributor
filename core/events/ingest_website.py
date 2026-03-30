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
    """Result of a website ingestion run."""

    timestamp: int = Field(
        default_factory=lambda: int(time.time() * 1000)
    )
    result: IngestionResult = IngestionResult.SUCCESS
    error: str = ""
