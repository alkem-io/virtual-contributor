"""Guidance re-ranking: fairness across three collections, and the funnel.

Guidance is the strongest case for this feature, for a reason the story does
not mention: it merges candidates from three separately-populated collections
by sorting on distance, and those distances are only loosely comparable. A
sparse corpus returns systematically worse distances, so its passages lose
every comparison regardless of how well they answer the question.
"""

from __future__ import annotations

from core.domain.rerank import LexicalReranker
from core.ports.knowledge_store import QueryResult
from plugins.guidance.plugin import GuidancePlugin
from tests.conftest import MockKnowledgeStorePort, MockLLMPort, make_input


class _ThreeCollectionStore(MockKnowledgeStorePort):
    """Three collections; the sparse one holds the actual answer.

    Its distances run systematically worse, so on distance alone its passages
    are shut out of the context window entirely.
    """

    _CORPUS: dict[str, tuple[list[str], list[float]]] = {
        "alkem.io-knowledge": (
            ["Alkemio is a platform for collaboration on societal challenges.",
             "Our mission is to enable collective action."],
            [0.10, 0.12],
        ),
        "welcome.alkem.io-knowledge": (
            ["Welcome to Alkemio. Start by exploring spaces.",
             "Spaces group people around a shared challenge."],
            [0.14, 0.16],
        ),
        "www.alkemio.org-knowledge": (
            ["To invite members to a space, open Space settings and click Invite.",
             "Member roles determine who can invite others to a space."],
            [0.45, 0.48],
        ),
    }

    async def query(
        self, collection: str, query_texts: list[str], n_results: int = 10,
    ) -> QueryResult:
        self.query_calls.append((collection, query_texts, n_results))
        docs, distances = self._CORPUS.get(collection, ([], []))
        keep = min(n_results, len(docs))
        return QueryResult(
            documents=[docs[:keep]],
            metadatas=[[
                {"source": f"https://{collection}/{i}", "title": f"page {i}"}
                for i in range(keep)
            ]],
            distances=[distances[:keep]],
            ids=[[f"{collection}-{i}" for i in range(keep)]],
        )


class _OneCollectionRaises(_ThreeCollectionStore):
    async def query(
        self, collection: str, query_texts: list[str], n_results: int = 10,
    ) -> QueryResult:
        if collection == "alkem.io-knowledge":
            raise RuntimeError("collection unavailable")
        return await super().query(collection, query_texts, n_results)


class _DuplicateSourceStore(MockKnowledgeStorePort):
    """Several chunks from the same page, plus distinct pages.

    Truncating before dedupe would let the duplicates eat the budget.
    """

    async def query(
        self, collection: str, query_texts: list[str], n_results: int = 10,
    ) -> QueryResult:
        self.query_calls.append((collection, query_texts, n_results))
        if collection != "alkem.io-knowledge":
            return QueryResult(documents=[[]], metadatas=[[]], distances=[[]], ids=[[]])
        docs = [f"invite members chunk {i}" for i in range(4)] + [
            "another page about inviting members", "a third page on invitations",
        ]
        sources = ["https://example.org/same"] * 4 + [
            "https://example.org/second", "https://example.org/third",
        ]
        return QueryResult(
            documents=[docs],
            metadatas=[[{"source": s, "title": "t"} for s in sources]],
            distances=[[0.10, 0.11, 0.12, 0.13, 0.30, 0.32]],
            ids=[[f"id{i}" for i in range(6)]],
        )


def _plugin(store: MockKnowledgeStorePort, **kwargs: object) -> GuidancePlugin:
    return GuidancePlugin(
        llm=MockLLMPort(response="an answer"),
        knowledge_store=store,
        **kwargs,  # type: ignore[arg-type]
    )


QUESTION = "how do I invite members to a space"


class TestCrossCollectionFairness:
    async def test_sparse_collection_answer_can_win(self) -> None:
        """US2-AS1 — the merge stops being decided by corpus density."""
        store = _ThreeCollectionStore()
        plugin = _plugin(
            store, n_results=5, score_threshold=0.0,
            reranker=LexicalReranker(), rerank_candidate_n=5, rerank_top_k=5,
        )
        response = await plugin.handle(make_input(message=QUESTION))
        assert response.sources
        assert "www.alkemio.org-knowledge" in response.sources[0].uri

    async def test_without_reranking_the_sparse_collection_is_shut_out(self) -> None:
        """The defect this fixes, asserted so it cannot silently return."""
        store = _ThreeCollectionStore()
        plugin = _plugin(store, n_results=3, score_threshold=0.0)
        response = await plugin.handle(make_input(message=QUESTION))
        assert all(
            "www.alkemio.org-knowledge" not in (s.uri or "")
            for s in response.sources
        )


class TestFunnelOrder:
    async def test_k_distinct_sources_when_k_distinct_sources_exist(self) -> None:
        """SC-011 / R-4 — the trap: truncating before dedupe.

        Four chunks share one page. Cutting to top-K first would spend the
        budget on that one page and return fewer distinct sources.
        """
        store = _DuplicateSourceStore()
        plugin = _plugin(
            store, n_results=3, score_threshold=0.0,
            reranker=LexicalReranker(), rerank_candidate_n=10, rerank_top_k=3,
        )
        response = await plugin.handle(make_input(message=QUESTION))
        uris = [s.uri for s in response.sources]
        assert len(set(uris)) == len(uris)
        assert len(uris) == 3

    async def test_threshold_still_applies_to_the_vector_score(self) -> None:
        """FR-020 — the pool-relative blended score must not gate eligibility."""
        store = _ThreeCollectionStore()
        plugin = _plugin(
            store, n_results=5, score_threshold=0.7,
            reranker=LexicalReranker(), rerank_candidate_n=5, rerank_top_k=5,
        )
        response = await plugin.handle(make_input(message=QUESTION))
        # Distances >= 0.3 fail a 0.7 threshold, including the term-matching
        # chunks at 0.45/0.48 — despite re-ranking having placed them first.
        assert all(
            "www.alkemio.org-knowledge" not in (s.uri or "")
            for s in response.sources
        )

    async def test_source_scores_remain_vector_scores(self) -> None:
        """US2-AS3 — cited scores must stay meaningful, not pool-relative."""
        store = _ThreeCollectionStore()
        plugin = _plugin(
            store, n_results=5, score_threshold=0.0,
            reranker=LexicalReranker(), rerank_candidate_n=5, rerank_top_k=5,
        )
        response = await plugin.handle(make_input(message=QUESTION))
        expected = {round(1.0 - d, 6) for _, ds in
                    _ThreeCollectionStore._CORPUS.values() for d in ds}
        for source in response.sources:
            assert round(source.score or 0.0, 6) in expected


class TestResilience:
    async def test_failing_collection_is_still_swallowed(self) -> None:
        """US2-AS2 — one dead collection must not fail the whole answer."""
        store = _OneCollectionRaises()
        plugin = _plugin(
            store, n_results=5, score_threshold=0.0,
            reranker=LexicalReranker(), rerank_candidate_n=5, rerank_top_k=5,
        )
        response = await plugin.handle(make_input(message=QUESTION))
        assert response.sources
        assert all(
            not (s.uri or "").startswith("https://alkem.io-knowledge/")
            for s in response.sources
        )


class TestDisabledIsIdentical:
    async def test_disabled_requests_n_results(self) -> None:
        store = _ThreeCollectionStore()
        plugin = _plugin(store, n_results=5, rerank_candidate_n=20)
        await plugin.handle(make_input(message=QUESTION))
        assert all(call[2] == 5 for call in store.query_calls)

    async def test_enabled_requests_candidate_n(self) -> None:
        store = _ThreeCollectionStore()
        plugin = _plugin(
            store, n_results=5,
            reranker=LexicalReranker(), rerank_candidate_n=20, rerank_top_k=5,
        )
        await plugin.handle(make_input(message=QUESTION))
        assert all(call[2] == 20 for call in store.query_calls)

    async def test_enabling_adds_no_outbound_calls(self) -> None:
        """US4-AS4 — still three collection queries, no extra round trip."""
        off_store = _ThreeCollectionStore()
        off_llm = MockLLMPort(response="an answer")
        await GuidancePlugin(
            llm=off_llm, knowledge_store=off_store, n_results=5,
        ).handle(make_input(message=QUESTION))

        on_store = _ThreeCollectionStore()
        on_llm = MockLLMPort(response="an answer")
        await GuidancePlugin(
            llm=on_llm, knowledge_store=on_store, n_results=5,
            reranker=LexicalReranker(), rerank_candidate_n=5, rerank_top_k=5,
        ).handle(make_input(message=QUESTION))

        assert len(on_store.query_calls) == len(off_store.query_calls)
        assert len(on_llm.calls) == len(off_llm.calls)
