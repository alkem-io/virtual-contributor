"""Lexical scoring: does it reward the right passage, and never raise?"""

from __future__ import annotations

from core.domain.lexical_score import compute_idf, lexical_scores, tokenize


class TestTokenize:
    def test_lowercases_and_splits_on_punctuation(self) -> None:
        assert tokenize("Invite Members, to a Space!") == [
            "invite", "members", "to", "a", "space",
        ]

    def test_keeps_digits_so_identifiers_survive(self) -> None:
        assert tokenize("upgrade to v2 on k8s") == ["upgrade", "to", "v2", "on", "k8s"]

    def test_empty_text_yields_no_terms(self) -> None:
        assert tokenize("") == []


class TestComputeIdf:
    def test_rare_term_outweighs_ubiquitous_term(self) -> None:
        docs = [["space", "invite"]] + [["space", "overview"] for _ in range(19)]
        idf = compute_idf(docs)
        assert idf["invite"] > idf["space"]

    def test_ubiquitous_term_stays_non_negative(self) -> None:
        # A term in every candidate must score ~0, never below it: a negative
        # IDF would let a word common to everything actively demote a passage.
        idf = compute_idf([["space"], ["space"], ["space"]])
        assert idf["space"] >= 0.0

    def test_empty_candidate_set(self) -> None:
        assert compute_idf([]) == {}


class TestLexicalScores:
    def test_term_in_one_of_twenty_outscores_term_in_all_twenty(self) -> None:
        """The discriminating passage must win. This is the whole point."""
        docs = ["a space overview page" for _ in range(19)]
        docs.append("how to invite members to a space")
        scores = lexical_scores("invite members space", docs)
        assert scores[19] > max(scores[:19])

    def test_length_alone_does_not_win(self) -> None:
        """A long passage mentioning the term once must not beat a focused one."""
        focused = "invite members to a space"
        padded = "unrelated filler text. " * 100 + "invite members to a space"
        scores = lexical_scores("invite members space", [focused, padded])
        assert scores[0] > scores[1]

    def test_repetition_saturates(self) -> None:
        """Keyword stuffing must not beat a genuine answer outright."""
        stuffed = "invite invite invite invite invite invite invite invite"
        real = "to invite members to a space, open settings and click invite"
        scores = lexical_scores("invite members to a space", [stuffed, real])
        assert scores[1] > scores[0]

    def test_scores_are_bounded_to_unit_interval(self) -> None:
        docs = ["invite members space", "something else entirely", "invite"]
        assert all(0.0 <= s <= 1.0 for s in lexical_scores("invite members space", docs))

    # --- degenerate inputs: all must return zeros, none may raise ---

    def test_no_documents(self) -> None:
        assert lexical_scores("invite", []) == []

    def test_empty_query(self) -> None:
        assert lexical_scores("", ["invite members"]) == [0.0]

    def test_whitespace_only_query(self) -> None:
        assert lexical_scores("   \n\t ", ["invite members"]) == [0.0]

    def test_query_terms_absent_everywhere(self) -> None:
        assert lexical_scores("zzz qqq", ["invite members", "spaces"]) == [0.0, 0.0]

    def test_non_latin_script_degrades_to_zero_without_raising(self) -> None:
        """CJK gets no lexical signal (gap G-5).

        The failure mode must be "no opinion", not "wrong opinion" — the blend
        then falls back to vector order rather than to noise.
        """
        assert lexical_scores("如何邀请成员", ["邀请成员到空间", "其他内容"]) == [0.0, 0.0]

    def test_empty_documents_do_not_raise(self) -> None:
        assert lexical_scores("invite", ["", ""]) == [0.0, 0.0]
