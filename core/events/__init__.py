"""Public API for core event models."""

from core.events.base import EventBase
from core.events.ingest_space import (
    ErrorDetail,
    IngestBodyOfKnowledge,
    IngestBodyOfKnowledgeResult,
)
from core.events.ingest_website import (
    IngestionMode,
    IngestionResult,
    IngestWebsite,
    IngestWebsiteResult,
    SourceResult,
    WebsiteSource,
)
from core.events.input import (
    ExternalConfig,
    ExternalMetadata,
    HistoryItem,
    Input,
    InvocationOperation,
    MessageSenderRole,
    ResultHandler,
    ResultHandlerAction,
    RoomDetails,
)
from core.events.response import Response, Source

__all__ = [
    # base
    "EventBase",
    # input
    "ExternalConfig",
    "ExternalMetadata",
    "HistoryItem",
    "Input",
    "InvocationOperation",
    "MessageSenderRole",
    "ResultHandler",
    "ResultHandlerAction",
    "RoomDetails",
    # response
    "Response",
    "Source",
    # ingest – website
    "IngestionMode",
    "IngestionResult",
    "IngestWebsite",
    "IngestWebsiteResult",
    "SourceResult",
    "WebsiteSource",
    # ingest – space / body of knowledge
    "ErrorDetail",
    "IngestBodyOfKnowledge",
    "IngestBodyOfKnowledgeResult",
]
