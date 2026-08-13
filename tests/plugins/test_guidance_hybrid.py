"""Guidance retrieval with the lexical arm across three collections."""

from __future__ import annotations

from dataclasses import dataclass

from core.ports.knowledge_store import QueryResult
from plugins.guidance.plugin import DEFAULT_COLLECTIONS, GuidancePlugin
from tests.conftest import MockLLMPort, make_input


@dataclass
class _Hybrid:
    hybrid_retrieval_enabled: bool = True
    hybrid_dense_weight: float = 1.0
    hybrid_lexical_weight: float = 1.0
    hybrid_rrf_k: int = 60
    hybrid_max_terms: int = 8
    hybrid_min_term_len: int = 3


class _Store:
    """Every collection returns five unremarkable hits; one also has the term."""

    def __init__(self) -> None:
        self.lexical_calls: list[str] = []

    async def query(self, collection, query_texts, n_results=10):
        ids = [f"{collection}-x{n}" for n in range(5)]
        return QueryResult(
            documents=[[f"generic text {i}" for i in ids]],
            metadatas=[[{"source": i} for i in ids]],
            distances=[[0.2 + 0.05 * n for n in range(5)]],
            ids=[ids],
        )

    async def query_lexical(self, collection, terms, n_results=10):
        self.lexical_calls.append(collection)
        if collection != DEFAULT_COLLECTIONS[0]:
            return QueryResult(
                documents=[[]], metadatas=[[]], distances=[[]], ids=[[]],
            )
        return QueryResult(
            documents=[["The Traefik ingress controller terminates TLS."]],
            metadatas=[[{"source": "rare-url"}]],
            distances=[[None]],
            ids=[["rare-url"]],
        )


def _plugin(store, *, hybrid) -> GuidancePlugin:
    return GuidancePlugin(
        llm=MockLLMPort(response="answer"),
        knowledge_store=store,
        n_results=5,
        score_threshold=0.3,
        hybrid_config=hybrid,
    )


class TestLexicalReachesTheAnswer:
    async def test_the_term_bearing_passage_is_cited_at_default_settings(self):
        """Three collections each contribute hits; the cut must not lose it."""
        store = _Store()
        response = await _plugin(store, hybrid=_Hybrid()).handle(
            make_input(message="What does Traefik do?")
        )
        assert "rare-url" in {s.source for s in response.sources}

    async def test_it_carries_no_score(self):
        store = _Store()
        response = await _plugin(store, hybrid=_Hybrid()).handle(
            make_input(message="What does Traefik do?")
        )
        rare = [s for s in response.sources if s.source == "rare-url"]
        assert rare and rare[0].score is None

    async def test_every_collection_is_asked(self):
        store = _Store()
        await _plugin(store, hybrid=_Hybrid()).handle(
            make_input(message="What does Traefik do?")
        )
        assert sorted(store.lexical_calls) == sorted(DEFAULT_COLLECTIONS)


class TestDisabledParity:
    async def test_the_lexical_arm_is_never_consulted(self):
        store = _Store()
        await _plugin(store, hybrid=None).handle(
            make_input(message="What does Traefik do?")
        )
        assert store.lexical_calls == []

    async def test_sources_are_the_dense_ones(self):
        store = _Store()
        response = await _plugin(store, hybrid=None).handle(
            make_input(message="What does Traefik do?")
        )
        assert "rare-url" not in {s.source for s in response.sources}
        assert all(s.score is not None for s in response.sources)
