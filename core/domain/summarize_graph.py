"""Summarization graph — summarize-then-refine pattern using LangGraph."""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SummarizeState(BaseModel):
    """State for the summarization graph."""
    chunks: list[str] = Field(default_factory=list)
    index: int = 0
    summary: str = ""


async def summarize_document(
    chunks: list[str],
    llm_invoke,
    max_length: int = 10000,
) -> str:
    """Summarize a document using the refine pattern.

    Progressive length budgeting: early chunks get 40% of budget,
    scaling up to 100% for later chunks.
    """
    if not chunks:
        return ""

    if len(chunks) == 1:
        return chunks[0][:max_length]

    summary = ""
    for i, chunk in enumerate(chunks):
        # Progressive length budget: 40% → 100%
        progress = i / max(len(chunks) - 1, 1)
        budget = int(max_length * (0.4 + 0.6 * progress))

        if i == 0:
            prompt = (
                f"Summarize the following text in at most {budget} characters:\n\n"
                f"{chunk}"
            )
        else:
            prompt = (
                f"Given this existing summary:\n{summary}\n\n"
                f"And this additional text:\n{chunk}\n\n"
                f"Produce a refined summary in at most {budget} characters."
            )

        summary = await llm_invoke([{"role": "human", "content": prompt}])

    return summary


async def summarize_body_of_knowledge(
    document_summaries: list[str],
    llm_invoke,
    max_length: int = 10000,
) -> str:
    """Summarize an entire body of knowledge from document summaries."""
    return await summarize_document(document_summaries, llm_invoke, max_length)
