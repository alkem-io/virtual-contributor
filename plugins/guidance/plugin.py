"""GuidancePlugin — multi-collection RAG with score filtering."""

from __future__ import annotations

import json
import logging
import re

from core.events.input import Input
from core.events.response import Response, Source
from core.ports.llm import LLMPort
from core.ports.knowledge_store import KnowledgeStorePort

logger = logging.getLogger(__name__)

# Default collections for guidance
DEFAULT_COLLECTIONS = [
    "alkem.io-knowledge",
    "welcome.alkem.io-knowledge",
    "www.alkemio.org-knowledge",
]


class GuidancePlugin:
    """Multi-collection RAG guidance plugin.

    Condenses history, queries 3 knowledge collections, filters by
    relevance score, and generates a response with source references.
    """

    name = "guidance"
    event_type = Input

    def __init__(self, llm: LLMPort, knowledge_store: KnowledgeStorePort) -> None:
        self._llm = llm
        self._knowledge_store = knowledge_store

    async def startup(self) -> None:
        logger.info("GuidancePlugin started")

    async def shutdown(self) -> None:
        logger.info("GuidancePlugin stopped")

    async def handle(self, event: Input, **ports) -> Response:
        question = event.message
        language = event.language or "EN"

        # Condense history if present
        if event.history:
            from plugins.guidance.prompts import condense_prompt
            history_text = "\n".join(
                f"{h.role}: {h.content}" for h in event.history
            )
            condensed = await self._llm.invoke([{
                "role": "human",
                "content": condense_prompt.format(
                    chat_history=history_text, question=question
                ),
            }])
            question = condensed

        # Query multiple collections
        all_docs = []
        all_sources = []
        for collection in DEFAULT_COLLECTIONS:
            try:
                result = await self._knowledge_store.query(
                    collection=collection, query_texts=[question], n_results=5,
                )
                if result.documents:
                    for i, doc in enumerate(result.documents[0]):
                        distance = result.distances[0][i] if result.distances else 1.0
                        score = 1.0 - distance
                        if score >= 0.3:  # relevance filter
                            all_docs.append(doc)
                            meta = result.metadatas[0][i] if result.metadatas else {}
                            all_sources.append(Source(
                                source=meta.get("source", collection),
                                title=meta.get("title"),
                                uri=meta.get("uri"),
                                score=score,
                            ))
            except Exception:
                logger.warning("Failed to query collection %s", collection)

        context = "\n\n".join(all_docs) if all_docs else "No relevant context found."

        # Generate response
        from plugins.guidance.prompts import retrieve_prompt
        answer = await self._llm.invoke([{
            "role": "human",
            "content": retrieve_prompt.format(
                context=context, question=question, language=language
            ),
        }])

        # Try to parse JSON response for source scores
        parsed_sources = self._parse_json_sources(answer)
        if parsed_sources is not None:
            return Response(
                result=parsed_sources.get("answer", answer),
                sources=all_sources,
                human_language=language,
            )

        return Response(
            result=answer,
            sources=all_sources,
            human_language=language,
        )

    @staticmethod
    def _parse_json_sources(text: str) -> dict | None:
        """Try to parse LLM response as JSON, stripping markdown code fences if present."""
        if not isinstance(text, str):
            return None
        try:
            cleaned = re.sub(r'^```(?:json)?\s*\n?|\n?```\s*$', '', text.strip())
            return json.loads(cleaned)
        except (json.JSONDecodeError, TypeError):
            return None
