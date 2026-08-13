"""Term extraction for the lexical retrieval arm."""

from __future__ import annotations

from core.domain.query_terms import STOP_WORDS, extract_terms


def _terms(text: str, *, min_len: int = 3, max_terms: int = 8) -> list[str]:
    return extract_terms(text, min_len=min_len, max_terms=max_terms)


class TestExtractTerms:
    def test_keeps_the_distinctive_words(self):
        assert _terms("What is the Traefik ingress configuration?") == [
            "traefik", "ingress", "configuration",
        ]

    def test_drops_stop_words(self):
        assert _terms("what is the and or but") == []

    def test_casefolds(self):
        assert _terms("TRAEFIK Traefik traefik") == ["traefik"]

    def test_deduplicates_preserving_first_seen_order(self):
        assert _terms("beta alpha beta gamma alpha") == ["beta", "alpha", "gamma"]

    def test_min_len_boundary(self):
        """Length equal to the minimum is kept; one shorter is dropped."""
        assert _terms("abc", min_len=3) == ["abc"]
        assert _terms("ab", min_len=3) == []

    def test_truncates_to_max_terms(self):
        text = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
        assert _terms(text, max_terms=4) == ["alpha", "beta", "gamma", "delta"]

    def test_punctuation_only_yields_nothing(self):
        assert _terms("??? --- !!!") == []

    def test_empty_input_yields_nothing(self):
        assert _terms("") == []

    def test_digits_survive(self):
        """Version numbers and identifiers are exactly what this arm is for."""
        assert "v2" in extract_terms("upgrade to v2", min_len=2, max_terms=8)
        assert "2024" in _terms("the 2024 annual report")

    def test_punctuation_splits_rather_than_corrupts(self):
        assert _terms("kubernetes/traefik-ingress") == [
            "kubernetes", "traefik", "ingress",
        ]

    def test_stop_word_list_is_lowercase_and_non_empty(self):
        assert STOP_WORDS
        assert all(w == w.casefold() for w in STOP_WORDS)
