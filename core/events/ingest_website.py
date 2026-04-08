"""Website ingestion event models."""

from __future__ import annotations

import json
import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.events.base import EventBase


class IngestionResult(str, Enum):
    """Outcome of a website ingestion run."""

    SUCCESS = "success"
    FAILURE = "failure"


class IngestionMode(str, Enum):
    """Whether to wipe the collection first or incrementally update."""

    FULL = "FULL"
    INCREMENTAL = "INCREMENTAL"


class WebsiteSource(BaseModel):
    """A single website source to crawl with per-source parameters."""

    model_config = ConfigDict(populate_by_name=True)

    url: str
    page_limit: int = Field(default=20, alias="pageLimit")
    max_depth: int = Field(default=-1, alias="maxDepth")
    include_patterns: list[str] | None = Field(
        default=None, alias="includePatterns"
    )
    exclude_patterns: list[str] | None = Field(
        default=None, alias="excludePatterns"
    )

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("by_alias", True)
        return super().model_dump(**kwargs)


class IngestWebsite(EventBase):
    """Request to crawl and ingest a website into the knowledge base.

    Supports two payload shapes:
    - **Legacy**: ``{"baseUrl": "...", "type": "...", ...}`` (single URL,
      backward compatible with the existing message format).
    - **Enriched**: ``{"sources": [...], "mode": "FULL", ...}`` (multi-source
      with per-source crawl parameters).

    When only ``baseUrl`` is provided, a model_validator synthesises a
    single-element ``sources`` list with default crawl parameters.
    """

    # Legacy fields (kept for backward compatibility)
    base_url: str | None = Field(default=None, alias="baseUrl")
    type: str = ""
    purpose: str = ""
    persona_id: str = Field(default="", alias="personaId")
    summarization_model: str = Field(
        default="mistral-medium", alias="summarizationModel"
    )

    # New fields
    sources: list[WebsiteSource] | None = None
    mode: IngestionMode = Field(default=IngestionMode.INCREMENTAL)

    @model_validator(mode="after")
    def _normalise_sources(self) -> IngestWebsite:
        """Ensure ``sources`` is populated — synthesise from ``baseUrl`` if needed."""
        if not self.sources and self.base_url:
            self.sources = [WebsiteSource(url=self.base_url)]
        return self

    def get_source_config_json(self) -> str:
        """Serialise the resolved source list as JSON for metadata storage."""
        sources = self.sources or []
        return json.dumps([s.model_dump() for s in sources])


class IngestWebsiteResult(EventBase):
    """Result of a website ingestion run."""

    timestamp: int = Field(
        default_factory=lambda: int(time.time() * 1000)
    )
    result: IngestionResult = IngestionResult.SUCCESS
    error: str = ""


class IngestWebsiteProgress(EventBase):
    """Progress update emitted during website ingestion.

    Defined for future use when the message handler passes
    the transport port to the plugin's handle method.
    """

    source_url: str = Field(alias="sourceUrl")
    status: str  # CRAWLING, SUMMARIZING, EMBEDDING, STORING, COMPLETED, FAILED
    pages_crawled: int = Field(default=0, alias="pagesCrawled")
    chunks_processed: int = Field(default=0, alias="chunksProcessed")
