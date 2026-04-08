"""Website ingestion event models."""

from __future__ import annotations

import time
from enum import Enum

from pydantic import Field, model_validator

from core.events.base import EventBase


class IngestionResult(str, Enum):
    """Outcome of a website ingestion run."""

    SUCCESS = "success"
    FAILURE = "failure"


class IngestionMode(str, Enum):
    """Ingestion mode: FULL wipes the collection first, INCREMENTAL is additive."""

    FULL = "full"
    INCREMENTAL = "incremental"


class WebsiteSource(EventBase):
    """Configuration for a single website source to crawl."""

    url: str
    page_limit: int | None = Field(default=None, alias="pageLimit")
    max_depth: int = Field(default=-1, alias="maxDepth")
    include_patterns: list[str] | None = Field(
        default=None, alias="includePatterns"
    )
    exclude_patterns: list[str] | None = Field(
        default=None, alias="excludePatterns"
    )


class SourceResult(EventBase):
    """Per-source crawl result for job status reporting."""

    url: str
    pages_processed: int = Field(default=0, alias="pagesProcessed")
    error: str = ""


class IngestWebsite(EventBase):
    """Request to crawl and ingest a website into the knowledge base."""

    # Legacy field (backward compat)
    base_url: str | None = Field(default=None, alias="baseUrl")
    # New structured sources
    sources: list[WebsiteSource] = Field(default_factory=list)
    mode: IngestionMode = Field(default=IngestionMode.INCREMENTAL)
    # Existing fields with defaults for new-format compat
    type: str = "website"
    purpose: str = "knowledge"
    persona_id: str = Field(alias="personaId")
    summarization_model: str = Field(
        default="mistral-medium", alias="summarizationModel"
    )

    @model_validator(mode="after")
    def _normalize_sources(self) -> IngestWebsite:
        """Synthesize sources from legacy baseUrl when sources list is empty."""
        if not self.sources and self.base_url:
            self.sources = [WebsiteSource(url=self.base_url)]
        return self


class IngestWebsiteResult(EventBase):
    """Result of a website ingestion run."""

    timestamp: int = Field(
        default_factory=lambda: int(time.time() * 1000)
    )
    result: IngestionResult = IngestionResult.SUCCESS
    error: str = ""
    source_results: list[SourceResult] = Field(
        default_factory=list, alias="sourceResults"
    )
