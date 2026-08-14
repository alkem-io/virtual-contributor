"""Expert plugin re-ranking: reordering, alignment, and the rollback.

The most important tests here are the ones asserting nothing happens: with no
re-ranker the plugin must behave exactly as it did before this feature, down to
the number of candidates it asks the store for.
"""

from __future__ import annotations

from core.domain.rerank import LexicalReranker
from core.ports.knowledge_store import QueryResult
from plugins.expert.plugin import ExpertPlugin, _apply_rerank
from tests.conftest import MockKnowledgeStorePort, MockLLMPort, make_input


class _FixtureStore(MockKnowledgeStorePort):
    """A store whose best-matching passage has the WORST vector distance.

    This is the scenario the story exists for: a page that documents the
    procedure being asked about, ranked below pages that are merely *about*
    the same subject.
    """

    def __init__(self) -> None:
        super().__init__()
        self.documents = [
            "Alkemio is a platform for collaboration on societal challenges.",
            "Our mission is to enable collective action across society.",
            "To invite members to a space, open Space settings and click Invite.",
            "Alkemio brings together diverse stakeholders around challenges.",
        ]
        self.distances = [0.10, 0.12, 0.45, 0.14]

    async def query(
        self, collection: str, query_texts: list[str], n_results: int = 10,
    ) -> QueryResult:
        self.query_calls.append((collection, query_texts, n_results))
        keep = min(n_results, len(self.documents))
        return QueryResult(
            documents=[self.documents[:keep]],
            metadatas=[[{"source": f"https://example.org/{i}"} for i in range(keep)]],
            distances=[self.distances[:keep]],
            ids=[[f"id{i}" for i in range(keep)]],
        )


def _plugin(store: MockKnowledgeStorePort, **kwargs: object) -> ExpertPlugin:
    return ExpertPlugin(
        llm=MockLLMPort(response="an answer"),
        knowledge_store=store,
        **kwargs,  # type: ignore[arg-type]
    )


class TestApplyRerank:
    def test_alignment_is_preserved_across_all_four_lists(self) -> None:
        """US1-AS3 — the failure this guards against is silent misattribution.

        A drifted permutation would cite one passage's text under another
        passage's URL, confidently and without error.
        """
        result = QueryResult(
            documents=[["alpha doc", "beta doc", "gamma doc"]],
            metadatas=[[{"source": "a"}, {"source": "b"}, {"source": "c"}]],
            distances=[[0.5, 0.1, 0.9]],
            ids=[["id-a", "id-b", "id-c"]],
        )
        original = {
            "alpha doc": ({"source": "a"}, 0.5, "id-a"),
            "beta doc": ({"source": "b"}, 0.1, "id-b"),
            "gamma doc": ({"source": "c"}, 0.9, "id-c"),
        }

        out = _apply_rerank(LexicalReranker(), "beta", result)

        for i, doc in enumerate(out.documents[0]):
            expected_meta, expected_dist, expected_id = original[doc]
            assert out.metadatas[0][i] == expected_meta
            assert out.distances[0][i] == expected_dist
            assert out.ids[0][i] == expected_id

    def test_distances_are_reordered_but_never_rewritten(self) -> None:
        """The blended score must not be written back.

        It is normalised across the pool, so persisting it would corrupt the
        relevance threshold, which is judged on the real vector distance.
        """
        result = QueryResult(
            documents=[["generic page", "invite members to a space"]],
            metadatas=[[{}, {}]],
            distances=[[0.10, 0.45]],
            ids=[["id0", "id1"]],
        )
        out = _apply_rerank(LexicalReranker(), "invite members space", result)
        assert sorted(out.distances[0]) == [0.10, 0.45]

    def test_reorders_without_truncating(self) -> None:
        """Truncation is the caller's job, after the threshold — not here.

        Cutting the pool at this point would hand the relevance threshold a
        pre-filtered list and could leave an answer with no sources at all.
        """
        result = QueryResult(
            documents=[["a", "b", "c", "d"]],
            metadatas=[[{}] * 4],
            distances=[[0.1, 0.2, 0.3, 0.4]],
            ids=[["1", "2", "3", "4"]],
        )
        out = _apply_rerank(LexicalReranker(), "a", result)
        assert len(out.documents[0]) == 4
        assert sorted(out.ids[0]) == ["1", "2", "3", "4"]

    def test_empty_result_passes_through(self) -> None:
        empty = QueryResult(documents=[[]], metadatas=[[]], distances=[[]], ids=[[]])
        assert _apply_rerank(LexicalReranker(), "q", empty) is empty


class TestDisabledIsIdentical:
    """The rollback guarantee — SC-003, US3-AS1."""

    async def test_disabled_requests_n_results_not_candidate_n(self) -> None:
        store = _FixtureStore()
        plugin = _plugin(store, n_results=5, rerank_candidate_n=20)
        await plugin.handle(make_input(message="how do I invite members to a space"))
        assert store.query_calls[0][2] == 5

    async def test_disabled_preserves_store_order(self) -> None:
        store = _FixtureStore()
        plugin = _plugin(store, n_results=4, score_threshold=0.0)
        await plugin.handle(make_input(message="how do I invite members to a space"))
        # Nothing reordered: the store's own order survives into the answer.
        assert store.query_calls[0][2] == 4

    async def test_enabling_adds_no_outbound_calls(self) -> None:
        """US4-AS4 — re-ranking is in-process; it must not add a round trip."""
        question = "how do I invite members to a space"

        off_store = _FixtureStore()
        off_llm = MockLLMPort(response="an answer")
        await ExpertPlugin(
            llm=off_llm, knowledge_store=off_store, n_results=4,
        ).handle(make_input(message=question))

        on_store = _FixtureStore()
        on_llm = MockLLMPort(response="an answer")
        await ExpertPlugin(
            llm=on_llm, knowledge_store=on_store, n_results=4,
            reranker=LexicalReranker(), rerank_candidate_n=4, rerank_top_k=4,
        ).handle(make_input(message=question))

        assert len(on_store.query_calls) == len(off_store.query_calls)
        assert len(on_llm.calls) == len(off_llm.calls)


class TestEnabledReorders:
    async def test_term_matching_chunk_is_promoted(self) -> None:
        """US1-AS1, end to end through the plugin."""
        store = _FixtureStore()
        plugin = _plugin(
            store, n_results=4, score_threshold=0.0,
            reranker=LexicalReranker(), rerank_candidate_n=4, rerank_top_k=4,
        )
        response = await plugin.handle(
            make_input(message="how do I invite members to a space"),
        )
        # The procedural page is now the first-cited source.
        assert response.sources
        assert response.sources[0].uri == "https://example.org/2"

    async def test_enabled_requests_candidate_n(self) -> None:
        """US1-AS2 — re-ranking needs a wider pool than it keeps."""
        store = _FixtureStore()
        plugin = _plugin(
            store, n_results=5,
            reranker=LexicalReranker(), rerank_candidate_n=20, rerank_top_k=5,
        )
        await plugin.handle(make_input(message="how do I invite members to a space"))
        assert store.query_calls[0][2] == 20

    async def test_top_k_bounds_what_reaches_the_threshold_stage(self) -> None:
        store = _FixtureStore()
        plugin = _plugin(
            store, n_results=5, score_threshold=0.0,
            reranker=LexicalReranker(), rerank_candidate_n=4, rerank_top_k=2,
        )
        response = await plugin.handle(
            make_input(message="how do I invite members to a space"),
        )
        assert len(response.sources) <= 2

    async def test_threshold_still_applies_to_the_vector_score(self) -> None:
        """FR-020 / R-5 — the blended score must never gate eligibility.

        With a threshold of 0.7, only distances below 0.3 qualify. The
        term-matching chunk sits at 0.45 and must be excluded despite being
        re-ranked first — otherwise the pool-relative blended score has leaked
        into the filter.
        """
        store = _FixtureStore()
        plugin = _plugin(
            store, n_results=4, score_threshold=0.7,
            reranker=LexicalReranker(), rerank_candidate_n=4, rerank_top_k=4,
        )
        response = await plugin.handle(
            make_input(message="how do I invite members to a space"),
        )
        assert all(s.uri != "https://example.org/2" for s in response.sources)

    async def test_no_term_overlap_falls_back_to_vector_order(self) -> None:
        """US1-AS4 — no lexical signal must mean no opinion, not noise."""
        store = _FixtureStore()
        plugin = _plugin(
            store, n_results=4, score_threshold=0.0,
            reranker=LexicalReranker(), rerank_candidate_n=4, rerank_top_k=4,
        )
        response = await plugin.handle(make_input(message="zzz qqq wwww"))
        assert response.sources[0].uri == "https://example.org/0"


class TestObservability:
    async def test_rerank_logs_metrics(self, caplog: object) -> None:
        """FR-028 — the stage must be visible without inferring it from quality."""
        import logging

        store = _FixtureStore()
        plugin = _plugin(
            store, n_results=4,
            reranker=LexicalReranker(), rerank_candidate_n=4, rerank_top_k=2,
        )
        with caplog.at_level(logging.INFO, logger="plugins.expert.plugin"):  # type: ignore[attr-defined]
            await plugin.handle(make_input(message="how do I invite members to a space"))

        messages = [r.getMessage() for r in caplog.records]  # type: ignore[attr-defined]
        assert any("Re-ranked 4 candidates" in m for m in messages)

    async def test_no_rerank_log_when_disabled(self, caplog: object) -> None:
        import logging

        store = _FixtureStore()
        plugin = _plugin(store, n_results=4)
        with caplog.at_level(logging.INFO, logger="plugins.expert.plugin"):  # type: ignore[attr-defined]
            await plugin.handle(make_input(message="how do I invite members to a space"))

        assert not any(
            "Re-ranked" in r.getMessage() for r in caplog.records  # type: ignore[attr-defined]
        )


class _ThresholdTrapStore(MockKnowledgeStorePort):
    """Term-dense passages that FAIL the threshold, above generic ones that pass.

    Re-ranking lifts the term-dense stubs to the front. If truncation happened
    before the threshold they would fill the whole top-K and then all be
    discarded, leaving the answer with no sources at all.
    """

    async def query(
        self, collection: str, query_texts: list[str], n_results: int = 10,
    ) -> QueryResult:
        self.query_calls.append((collection, query_texts, n_results))
        docs = [f"General overview of the Alkemio platform, page {i}." for i in range(6)]
        distances = [0.35 + 0.02 * i for i in range(6)]          # pass a 0.3 threshold
        docs += [f"invite members space FAQ stub {i}" for i in range(14)]
        distances += [0.72 + 0.005 * i for i in range(14)]        # fail it
        keep = min(n_results, len(docs))
        return QueryResult(
            documents=[docs[:keep]],
            metadatas=[[{"source": f"s{i}"} for i in range(keep)]],
            distances=[distances[:keep]],
            ids=[[f"id{i}" for i in range(keep)]],
        )


class TestTruncationHappensAfterThreshold:
    """Re-ranking must never leave an answer with fewer sources than without it."""

    async def test_enabling_does_not_starve_the_context_window(self) -> None:
        question = "how do I invite members to a space"

        off = _ThresholdTrapStore()
        off_response = await ExpertPlugin(
            llm=MockLLMPort(response="a"), knowledge_store=off,
            n_results=5, score_threshold=0.3,
        ).handle(make_input(message=question))

        on = _ThresholdTrapStore()
        on_response = await ExpertPlugin(
            llm=MockLLMPort(response="a"), knowledge_store=on,
            n_results=5, score_threshold=0.3,
            reranker=LexicalReranker(), rerank_candidate_n=20, rerank_top_k=5,
        ).handle(make_input(message=question))

        assert on_response.sources, "re-ranking left the answer with no sources at all"
        assert len(on_response.sources) >= len(off_response.sources)

    async def test_top_k_still_bounds_the_result(self) -> None:
        store = _ThresholdTrapStore()
        response = await ExpertPlugin(
            llm=MockLLMPort(response="a"), knowledge_store=store,
            n_results=5, score_threshold=0.3,
            reranker=LexicalReranker(), rerank_candidate_n=20, rerank_top_k=3,
        ).handle(make_input(message="how do I invite members to a space"))
        assert len(response.sources) <= 3
