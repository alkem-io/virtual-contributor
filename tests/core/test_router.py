"""Unit tests for Content-Based Router."""

from __future__ import annotations

import pytest

from core.events.ingest_space import IngestBodyOfKnowledge
from core.events.ingest_website import IngestWebsite
from core.events.input import Input
from core.events.response import Response
from core.router import Router, RouterError
from tests.conftest import make_input, make_ingest_website, make_response


class TestRouterParseEvent:
    def test_input_routing_via_body_input(self):
        router = Router(plugin_type="generic")
        body = {"input": make_input().model_dump()}
        event = router.parse_event(body)
        assert isinstance(event, Input)
        assert event.message == "What is Alkemio?"

    def test_ingest_website_routing_via_event_type(self):
        router = Router(plugin_type="ingest-website")
        body = make_ingest_website().model_dump()
        body["eventType"] = "IngestWebsite"
        event = router.parse_event(body)
        assert isinstance(event, IngestWebsite)
        assert event.base_url == "https://example.com"

    def test_ingest_body_of_knowledge_routing(self):
        router = Router(plugin_type="ingest-space")
        body = {
            "bodyOfKnowledgeId": "bok-123",
            "type": "alkemio-space",
            "purpose": "knowledge",
            "personaId": "p1",
        }
        event = router.parse_event(body)
        assert isinstance(event, IngestBodyOfKnowledge)
        assert event.body_of_knowledge_id == "bok-123"

    def test_unknown_type_missing_input_key(self):
        router = Router(plugin_type="generic")
        with pytest.raises(RouterError, match="missing 'input' key"):
            router.parse_event({"bad": "data"})

    def test_malformed_message_raises(self):
        router = Router(plugin_type="generic")
        with pytest.raises(RouterError):
            router.parse_event({"input": {"not": "valid"}})


class TestRouterResponseEnvelope:
    def test_engine_query_envelope_has_original(self):
        router = Router(plugin_type="generic")
        inp = make_input()
        resp = make_response()
        envelope = router.build_response_envelope(resp, inp)
        assert "response" in envelope
        assert "original" in envelope
        assert envelope["response"]["result"] == "Test response"

    def test_ingest_envelope_no_original(self):
        router = Router(plugin_type="ingest-website")
        event = make_ingest_website()
        from core.events.ingest_website import IngestWebsiteResult

        result = IngestWebsiteResult()
        envelope = router.build_response_envelope(result, event)
        assert "response" in envelope
        assert "original" not in envelope
