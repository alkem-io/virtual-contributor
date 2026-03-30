"""Unit tests for summarize graph."""

from __future__ import annotations

import pytest

from core.domain.summarize_graph import summarize_document, summarize_body_of_knowledge


class MockLLMInvoke:
    def __init__(self, response="Summary"):
        self.response = response
        self.calls = []

    async def __call__(self, messages):
        self.calls.append(messages)
        return self.response


class TestSummarizeDocument:
    async def test_empty_chunks(self):
        llm = MockLLMInvoke()
        result = await summarize_document([], llm)
        assert result == ""

    async def test_single_chunk_passthrough(self):
        llm = MockLLMInvoke()
        result = await summarize_document(["Single chunk content"], llm)
        assert result == "Single chunk content"
        assert len(llm.calls) == 0  # No LLM call for single chunk

    async def test_refine_pattern_iteration(self):
        llm = MockLLMInvoke(response="Refined summary")
        chunks = ["Chunk 1", "Chunk 2", "Chunk 3"]
        result = await summarize_document(chunks, llm)
        assert result == "Refined summary"
        assert len(llm.calls) == 3  # One call per chunk

    async def test_progressive_length_budgeting(self):
        llm = MockLLMInvoke(response="Summary")
        chunks = ["A" * 5000, "B" * 5000, "C" * 5000]
        await summarize_document(chunks, llm, max_length=10000)
        # First call should mention ~4000 chars (40%), last ~10000 (100%)
        first_prompt = llm.calls[0][0]["content"]
        assert "4000" in first_prompt  # 40% of 10000
        last_prompt = llm.calls[-1][0]["content"]
        assert "10000" in last_prompt  # 100% of 10000


class TestSummarizeBodyOfKnowledge:
    async def test_aggregates_summaries(self):
        llm = MockLLMInvoke(response="BoK summary")
        summaries = ["Doc 1 summary", "Doc 2 summary"]
        result = await summarize_body_of_knowledge(summaries, llm)
        assert result == "BoK summary"
