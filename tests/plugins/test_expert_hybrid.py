"""Expert retrieval with the lexical arm: what it finds, and what it preserves."""

from __future__ import annotations

from dataclasses import dataclass

from core.events.input import Input
from core.ports.knowledge_store import QueryResult
from plugins.expert.plugin import ExpertPlugin
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
    """Mock whose dense arm deliberately ranks the term-bearing passage last.

    That is the situation this feature exists for: a passage whose wording
    matches exactly but whose embedding similarity is unremarkable.
    """

    def __init__(self, dense_ids: list[str], corpus: dict[str, str]):
        super().__init__()
        self._dense_ids = dense_ids
        self._corpus = corpus
        self.collections["c-knowledge"] = [
            {"id": i, "document": text, "metadata": {"documentId": i, "source": i}}
            for i, text in corpus.items()
        ]

    async def query(self, collection, query_texts, n_results=10, where=None):
        self.query_calls.append((collection, query_texts, n_results))
        ids = self._dense_ids[:n_results]
        return QueryResult(
            documents=[[self._corpus[i] for i in ids]],
            metadatas=[[{"documentId": i, "source": i} for i in ids]],
            distances=[[0.2 + 0.1 * n for n in range(len(ids))]],
            ids=[list(ids)],
        )


def _plugin(store, *, hybrid) -> ExpertPlugin:
    return ExpertPlugin(
        llm=MockLLMPort(response="answer"),
        knowledge_store=store,
        n_results=3,
        score_threshold=0.3,
        hybrid_config=hybrid,
    )


def _event(message: str) -> Input:
    return make_input(message=message, bodyOfKnowledgeID="c")


CORPUS = {
    "d1": "General discussion about infrastructure and networking topics.",
    "d2": "Notes on deployment strategy and rollout planning.",
    "d3": "The Traefik ingress controller terminates TLS at the edge.",
}


class TestExactTermRetrieval:
    async def test_term_bearing_passage_is_retrieved_and_cited(self):
        """Dense ranks it last and the budget would cut it — lexical rescues it."""
        store = _Store(dense_ids=["d1", "d2"], corpus=CORPUS)
        response = await _plugin(store, hybrid=_Hybrid()).handle(
            _event("What does Traefik do?")
        )
        cited = {s.source for s in response.sources}
        assert "d3" in cited

    async def test_casing_does_not_matter_in_either_direction(self):
        for query in ("traefik", "TRAEFIK", "TrAeFiK"):
            store = _Store(dense_ids=["d1"], corpus=CORPUS)
            response = await _plugin(store, hybrid=_Hybrid()).handle(
                _event(f"Tell me about {query}")
            )
            assert "d3" in {s.source for s in response.sources}, query

    async def test_a_lexical_only_passage_has_no_score(self):
        """It was not matched by similarity, so there is no similarity to report."""
        store = _Store(dense_ids=["d1"], corpus=CORPUS)
        response = await _plugin(store, hybrid=_Hybrid()).handle(
            _event("Tell me about Traefik")
        )
        lexical = [s for s in response.sources if s.source == "d3"]
        assert lexical and lexical[0].score is None

    async def test_punctuation_in_a_query_does_not_break_retrieval(self):
        """A member's own punctuation must never error their own search."""
        for query in ("What about C++?", "the [draft] policy", "a|b routing", "cost ~50%"):
            store = _Store(dense_ids=["d1"], corpus=CORPUS)
            response = await _plugin(store, hybrid=_Hybrid()).handle(_event(query))
            assert response.result == "answer", query


class TestDisabledParity:
    """With the flag off, retrieval must be what it was before this feature."""

    async def test_same_sources_as_the_dense_path(self):
        off_store = _Store(dense_ids=["d1", "d2"], corpus=CORPUS)
        off = await _plugin(off_store, hybrid=None).handle(
            _event("What does Traefik do?")
        )
        assert [s.source for s in off.sources] == ["d1", "d2"]

    async def test_the_lexical_arm_is_never_consulted(self):
        store = _Store(dense_ids=["d1", "d2"], corpus=CORPUS)
        await _plugin(store, hybrid=None).handle(_event("What does Traefik do?"))
        assert store.lexical_calls == []

    async def test_explicitly_disabled_matches_absent_config(self):
        a = _Store(dense_ids=["d1", "d2"], corpus=CORPUS)
        b = _Store(dense_ids=["d1", "d2"], corpus=CORPUS)
        r_none = await _plugin(a, hybrid=None).handle(_event("Traefik?"))
        r_off = await _plugin(
            b, hybrid=_Hybrid(hybrid_retrieval_enabled=False),
        ).handle(_event("Traefik?"))
        assert [s.source for s in r_none.sources] == [s.source for s in r_off.sources]
        assert b.lexical_calls == []


class TestConceptualQueriesAreUnharmed:
    async def test_dense_results_survive_fusion(self):
        """Adding an arm must not remove what the other one found."""
        store = _Store(dense_ids=["d1", "d2"], corpus=CORPUS)
        response = await _plugin(store, hybrid=_Hybrid()).handle(
            _event("How should we plan the rollout?")
        )
        cited = {s.source for s in response.sources}
        assert {"d1", "d2"} <= cited


class TestRaggedDistancesKeepDevelopBehaviour:
    """A missing distance is not the same as an absent one.

    An explicit None means "matched literally" and is exempt from the semantic
    threshold. A distance simply missing from a short list is a malformed
    result, which scored zero and was dropped before this feature — and must
    still be, or turning the flag off would not restore prior behaviour.
    """

    @staticmethod
    def _kept(distances: list, threshold: float = 0.3) -> list[str]:
        from plugins.expert.plugin import _filter_and_format

        result = QueryResult(
            documents=[["a", "b"]], metadatas=[[{}, {}]],
            distances=[distances], ids=[["i1", "i2"]],
        )
        _, filtered = _filter_and_format(result, threshold)
        return filtered.documents[0]

    def test_no_distances_drops_everything_as_before(self):
        assert self._kept([]) == []

    def test_a_short_distance_list_drops_the_unmeasured_tail(self):
        assert self._kept([0.1]) == ["a"]

    def test_an_explicit_none_is_still_exempt(self):
        assert self._kept([0.1, None]) == ["a", "b"]

    def test_a_high_distance_is_still_filtered(self):
        assert self._kept([0.1, 0.95]) == ["a"]
