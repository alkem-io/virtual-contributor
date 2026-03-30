"""Contract tests for event models: camelCase serialization, round-trip, enum values."""

from __future__ import annotations

import json


from core.events import (
    ErrorDetail,
    HistoryItem,
    IngestBodyOfKnowledge,
    IngestBodyOfKnowledgeResult,
    IngestionResult,
    IngestWebsite,
    IngestWebsiteResult,
    Input,
    InvocationOperation,
    MessageSenderRole,
    Response,
    ResultHandlerAction,
    RoomDetails,
    Source,
)
from tests.conftest import (
    make_ingest_body_of_knowledge,
    make_ingest_website,
    make_input,
    make_response,
)


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class TestInputSerialization:
    def test_camel_case_aliases(self):
        inp = make_input()
        dumped = inp.model_dump()
        assert "userID" in dumped
        assert "personaID" in dumped
        assert "displayName" in dumped
        assert "resultHandler" in dumped
        assert "user_id" not in dumped

    def test_round_trip(self):
        inp = make_input(
            history=[{"content": "hi", "role": "human"}],
            externalConfig={"apiKey": "sk-test", "assistantId": "ast-1", "model": "gpt-4o"},
            externalMetadata={"threadId": "thr-1"},
        )
        dumped = inp.model_dump()
        restored = Input.model_validate(dumped)
        assert restored.message == inp.message
        assert restored.user_id == inp.user_id
        assert restored.external_config.api_key == "sk-test"
        assert restored.external_metadata.thread_id == "thr-1"
        assert len(restored.history) == 1
        assert restored.history[0].role == "human"

    def test_json_round_trip(self):
        inp = make_input()
        json_str = inp.model_dump_json()
        parsed = json.loads(json_str)
        assert "userID" in parsed
        restored = Input.model_validate_json(json_str)
        assert restored.user_id == inp.user_id

    def test_populate_by_name(self):
        """Can construct using Python field names (populate_by_name=True)."""
        inp = Input(
            engine="test",
            user_id="u1",
            message="hello",
            persona_id="p1",
        )
        assert inp.user_id == "u1"

    def test_envelope_format(self):
        """Engine queries use {"input": {...}} wrapper."""
        inp = make_input()
        envelope = {"input": inp.model_dump()}
        assert "input" in envelope
        restored = Input.model_validate(envelope["input"])
        assert restored.message == inp.message


# ---------------------------------------------------------------------------
# Enum values
# ---------------------------------------------------------------------------


class TestEnumValues:
    def test_message_sender_role_human(self):
        """Role uses 'human' not 'user'."""
        item = HistoryItem(content="hi", role=MessageSenderRole.HUMAN)
        dumped = item.model_dump()
        assert dumped["role"] == "human"

    def test_message_sender_role_assistant(self):
        item = HistoryItem(content="hello", role=MessageSenderRole.ASSISTANT)
        dumped = item.model_dump()
        assert dumped["role"] == "assistant"

    def test_invocation_operation_values(self):
        assert InvocationOperation.QUERY.value == "query"
        assert InvocationOperation.INGEST.value == "ingest"

    def test_result_handler_action_values(self):
        assert ResultHandlerAction.POST_REPLY.value == "postReply"
        assert ResultHandlerAction.POST_MESSAGE.value == "postMessage"
        assert ResultHandlerAction.NONE.value == "none"

    def test_ingestion_result_values(self):
        assert IngestionResult.SUCCESS.value == "success"
        assert IngestionResult.FAILURE.value == "failure"


# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------


class TestResponseSerialization:
    def test_camel_case(self):
        resp = make_response(
            humanLanguage="EN",
            sources=[{"chunkIndex": 0, "documentId": "d1", "score": 0.9}],
            threadId="thr-1",
        )
        dumped = resp.model_dump()
        assert "humanLanguage" in dumped
        assert "threadId" in dumped
        assert dumped["sources"][0]["chunkIndex"] == 0
        assert dumped["sources"][0]["documentId"] == "d1"

    def test_round_trip(self):
        resp = Response(result="answer", sources=[Source(score=0.85, uri="https://x.com")])
        dumped = resp.model_dump()
        restored = Response.model_validate(dumped)
        assert restored.result == "answer"
        assert restored.sources[0].score == 0.85

    def test_response_envelope(self):
        """Published response wraps in {"response": {...}, "original": {...}}."""
        resp = make_response()
        inp = make_input()
        envelope = {"response": resp.model_dump(), "original": inp.model_dump()}
        assert "response" in envelope
        assert "original" in envelope
        assert envelope["response"]["result"] == "Test response"


# ---------------------------------------------------------------------------
# RoomDetails
# ---------------------------------------------------------------------------


class TestRoomDetails:
    def test_camel_case_ids(self):
        rd = RoomDetails(
            room_id="r1", actor_id="a1", thread_id="t1", vc_interaction_id="v1"
        )
        dumped = rd.model_dump()
        assert dumped["roomID"] == "r1"
        assert dumped["actorID"] == "a1"
        assert dumped["threadID"] == "t1"
        assert dumped["vcInteractionID"] == "v1"


# ---------------------------------------------------------------------------
# IngestWebsite
# ---------------------------------------------------------------------------


class TestIngestWebsiteSerialization:
    def test_camel_case(self):
        event = make_ingest_website()
        dumped = event.model_dump()
        assert "baseUrl" in dumped
        assert "personaId" in dumped
        assert "summarizationModel" in dumped
        assert dumped["baseUrl"] == "https://example.com"

    def test_not_wrapped_in_input(self):
        """Ingest events are at the top level, no 'input' wrapper."""
        event = make_ingest_website()
        body = event.model_dump()
        assert "input" not in body

    def test_round_trip(self):
        event = make_ingest_website()
        dumped = event.model_dump()
        restored = IngestWebsite.model_validate(dumped)
        assert restored.base_url == event.base_url

    def test_result_model(self):
        result = IngestWebsiteResult()
        dumped = result.model_dump()
        assert dumped["result"] == "success"
        assert dumped["error"] == ""
        assert isinstance(dumped["timestamp"], int)

    def test_result_failure(self):
        result = IngestWebsiteResult(
            result=IngestionResult.FAILURE, error="Connection timeout"
        )
        dumped = result.model_dump()
        assert dumped["result"] == "failure"
        assert dumped["error"] == "Connection timeout"


# ---------------------------------------------------------------------------
# IngestBodyOfKnowledge
# ---------------------------------------------------------------------------


class TestIngestBodyOfKnowledgeSerialization:
    def test_camel_case(self):
        event = make_ingest_body_of_knowledge()
        dumped = event.model_dump()
        assert "bodyOfKnowledgeId" in dumped
        assert "personaId" in dumped

    def test_round_trip(self):
        event = make_ingest_body_of_knowledge()
        dumped = event.model_dump()
        restored = IngestBodyOfKnowledge.model_validate(dumped)
        assert restored.body_of_knowledge_id == event.body_of_knowledge_id

    def test_result_model(self):
        result = IngestBodyOfKnowledgeResult(
            body_of_knowledge_id="bok-1",
            type="alkemio-space",
            purpose="knowledge",
            persona_id="p1",
        )
        dumped = result.model_dump()
        assert dumped["bodyOfKnowledgeId"] == "bok-1"
        assert dumped["result"] == "success"
        assert isinstance(dumped["timestamp"], int)

    def test_result_with_error(self):
        result = IngestBodyOfKnowledgeResult(
            body_of_knowledge_id="bok-1",
            type="alkemio-space",
            purpose="knowledge",
            persona_id="p1",
            result="failure",
            error=ErrorDetail(code="ERR_001", message="Space not found"),
        )
        dumped = result.model_dump()
        assert dumped["result"] == "failure"
        assert dumped["error"]["code"] == "ERR_001"
