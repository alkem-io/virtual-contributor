"""Guidance retrieval with the lexical arm across three collections."""

from __future__ import annotations

from dataclasses import dataclass

from core.ports.knowledge_store import QueryResult
from plugins.guidance.plugin import DEFAULT_COLLECTIONS, GuidancePlugin
from tests.conftest import MockKnowledgeStorePort, MockLLMPort, make_input


@dataclass
class _Hybrid:
    hybrid_retrieval_enabled: bool = True
    hybrid_dense_weight: float = 1.0
    hybrid_lexical_weight: float = 1.0
    hybrid_rrf_k: int = 60
    hybrid_max_terms: int = 8
    hybrid_min_term_len: int = 3


class _Store(MockKnowledgeStorePort):
    """Every collection returns five unremarkable hits; one also has the term.

    Extends the shared port mock — as the expert-side fake does — so both
    arms' call tracking comes from one place and the fake keeps satisfying
    ``KnowledgeStorePort``.
    """

    def __init__(self) -> None:
        super().__init__()
        self.lexical_calls: list[str] = []

    async def query(self, collection, query_texts, n_results=10):
        self.query_calls.append((collection, query_texts, n_results))
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


class _UnevenStore(MockKnowledgeStorePort):
    """Three collections whose dense hits differ sharply in quality.

    The point is the gap: collection 0's third-best hit still beats
    collection 1's best. Any ordering that interleaves the collections will
    rank them differently, and — because the list is truncated straight after —
    will also return a different set.
    """

    #: collection -> dense distances, lower is a closer match.
    DISTANCES = {
        DEFAULT_COLLECTIONS[0]: [0.05, 0.10, 0.15],
        DEFAULT_COLLECTIONS[1]: [0.50, 0.55, 0.60],
        DEFAULT_COLLECTIONS[2]: [0.60, 0.65, 0.66],
    }

    def __init__(self) -> None:
        super().__init__()
        self.lexical_calls: list[str] = []

    async def query(self, collection, query_texts, n_results=10):
        self.query_calls.append((collection, query_texts, n_results))
        distances = self.DISTANCES[collection][:n_results]
        ids = [f"{collection}#{i}" for i in range(len(distances))]
        return QueryResult(
            documents=[[f"text {i}" for i in ids]],
            metadatas=[[{"source": i} for i in ids]],
            distances=[distances],
            ids=[ids],
        )

    async def query_lexical(self, collection, terms, n_results=10):
        self.lexical_calls.append(collection)
        return QueryResult(documents=[[]], metadatas=[[]], distances=[[]], ids=[[]])


class TestDenseOnlyOrderingIsUnchanged:
    """With the feature off, ordering must be exactly what it was before it.

    Rank-first ordering interleaves the collections, so a weak collection's
    best hit displaces a strong collection's second and third. Since the list
    is cut to ``n_results`` immediately afterwards, that is not a reordering —
    it changes which sources ground the answer.
    """

    def _expected_by_global_score(self, limit: int) -> list[str]:
        scored = [
            (f"{c}#{i}", 1.0 - d)
            for c, ds in _UnevenStore.DISTANCES.items()
            for i, d in enumerate(ds)
        ]
        scored.sort(key=lambda p: -p[1])
        return [sid for sid, score in scored if score >= 0.3][:limit]

    async def test_sources_are_ordered_by_score_across_collections(self):
        store = _UnevenStore()
        response = await _plugin(store, hybrid=None).handle(
            make_input(message="What does Traefik do?")
        )
        assert [s.source for s in response.sources] == \
            self._expected_by_global_score(5)

    async def test_the_strong_collection_is_not_displaced_by_a_weak_one(self):
        """The specific regression: rank-first cost us two good passages."""
        store = _UnevenStore()
        response = await _plugin(store, hybrid=None).handle(
            make_input(message="What does Traefik do?")
        )
        returned = [s.source for s in response.sources]
        strong = DEFAULT_COLLECTIONS[0]
        assert f"{strong}#1" in returned
        assert f"{strong}#2" in returned

    async def test_hybrid_disabled_by_flag_orders_the_same_way(self):
        """Config present but switched off is the same rollback as no config."""
        store = _UnevenStore()
        off = _Hybrid(hybrid_retrieval_enabled=False)
        response = await _plugin(store, hybrid=off).handle(
            make_input(message="What does Traefik do?")
        )
        assert [s.source for s in response.sources] == \
            self._expected_by_global_score(5)


class TestHybridEnabledKeepsRankOrdering:
    async def test_rank_ordering_still_applies_when_enabled(self):
        """The fix must not undo what rank ordering was added to protect."""
        store = _Store()
        response = await _plugin(store, hybrid=_Hybrid()).handle(
            make_input(message="What does Traefik do?")
        )
        assert "rare-url" in {s.source for s in response.sources}
