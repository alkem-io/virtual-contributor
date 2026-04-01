"""Input event models – inbound invocation payload hierarchy."""

from __future__ import annotations

from enum import Enum

from pydantic import Field

from core.events.base import EventBase


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class MessageSenderRole(str, Enum):
    """Role of the message sender in conversation history."""

    HUMAN = "human"
    ASSISTANT = "assistant"


class InvocationOperation(str, Enum):
    """Top-level operation requested by the caller."""

    QUERY = "query"
    INGEST = "ingest"


class ResultHandlerAction(str, Enum):
    """How the platform should deliver the response."""

    POST_REPLY = "postReply"
    POST_MESSAGE = "postMessage"
    NONE = "none"


# ---------------------------------------------------------------------------
# Nested value objects
# ---------------------------------------------------------------------------

class HistoryItem(EventBase):
    """Single turn in the conversation history."""

    content: str
    role: MessageSenderRole


class RoomDetails(EventBase):
    """Platform room identifiers used for result delivery."""

    room_id: str = Field(alias="roomID")
    actor_id: str = Field(alias="actorID")
    thread_id: str = Field(alias="threadID")
    vc_interaction_id: str = Field(alias="vcInteractionID")


class ResultHandler(EventBase):
    """Describes how and where the result should be posted."""

    action: ResultHandlerAction
    room_details: RoomDetails | None = Field(default=None, alias="roomDetails")


class ExternalConfig(EventBase):
    """Optional external-provider configuration overrides."""

    api_key: str | None = Field(default=None, alias="apiKey")
    assistant_id: str | None = Field(default=None, alias="assistantId")
    model: str | None = None


class ExternalMetadata(EventBase):
    """External-provider metadata carried across invocations."""

    thread_id: str | None = Field(default=None, alias="threadId")


# ---------------------------------------------------------------------------
# Top-level input event
# ---------------------------------------------------------------------------

class Input(EventBase):
    """Full invocation payload received from the platform."""

    engine: str
    operation: InvocationOperation = Field(
        default=InvocationOperation.QUERY,
        alias="operation",
    )
    user_id: str = Field(alias="userID")
    message: str
    body_of_knowledge_id: str | None = Field(
        default=None, alias="bodyOfKnowledgeID"
    )
    context_id: str = Field(default="", alias="contextID")
    history: list[HistoryItem] = Field(default_factory=list)
    external_metadata: ExternalMetadata | None = Field(
        default=None, alias="externalMetadata"
    )
    external_config: ExternalConfig | None = Field(
        default=None, alias="externalConfig"
    )
    display_name: str = Field(default="", alias="displayName")
    description: str = ""
    persona_id: str = Field(default="", alias="personaID")
    language: str | None = "EN"
    result_handler: ResultHandler | None = Field(
        default=None, alias="resultHandler"
    )
    prompt: list[str] | None = None
    prompt_graph: dict | None = Field(default=None, alias="promptGraph")
