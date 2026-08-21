"""Byte-fidelity guard for the shipped golden set (R-1, spec-vc-3).

Re-parses the three vendored operator TSVs at test time — independently of
``scripts/build_golden_set.py`` — and asserts the shipped
``evaluation/golden/test_set.jsonl`` matches them exactly: same pairs, same
bytes, same category counts, and the shipped assertions are re-derivable
from the shipped answers. Nothing else in ``tests/`` reads either the
vendored TSVs or the shipped JSONL, so without this file a normalization
regression (NFC -> NFKC, or a wrong tab-split) ships silently: the full
suite stays green while the operator's exact wording is rewritten.

This test module deliberately re-implements the TSV parse (first-tab split,
NFC) rather than importing ``scripts/build_golden_set.py``'s ``_parse_tsv``
— importing it would let a bug in the parser hide from its own test.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

from evaluation.assertions import derive_assertions
from evaluation.dataset import load_test_set

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SOURCE_DIR = REPO_ROOT / "evaluation" / "golden" / "source"
TEST_SET_PATH = REPO_ROOT / "evaluation" / "golden" / "test_set.jsonl"
EVALUATIONS_DIR = REPO_ROOT / "evaluations"

# (source filename, category, expected row count) — mirrors
# scripts/build_golden_set.py's SOURCES, independently re-declared here so a
# change to one does not silently change the other unnoticed.
SOURCES: tuple[tuple[str, str, int], ...] = (
    ("cat1-documentation.tsv", "documentation", 38),
    ("cat2-building-alkemio.tsv", "building-alkemio", 8),
    ("cat3-design-thinker.tsv", "design-thinker", 25),
)


def _parse_tsv(path: Path) -> list[tuple[str, str]]:
    """Independently parse one vendored TSV: first-tab split, NFC only."""
    pairs: list[tuple[str, str]] = []
    raw_text = path.read_text(encoding="utf-8")
    lines = raw_text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    for line in lines:
        if not line:
            continue
        question, expected_answer = line.split("\t", 1)
        question = unicodedata.normalize("NFC", question)
        expected_answer = unicodedata.normalize("NFC", expected_answer)
        pairs.append((question, expected_answer))
    return pairs


def _vendored_pairs() -> list[tuple[str, str, str]]:
    """All (category, question, expected_answer) triples across the three TSVs."""
    triples: list[tuple[str, str, str]] = []
    for filename, category, _count in SOURCES:
        for question, expected_answer in _parse_tsv(SOURCE_DIR / filename):
            triples.append((category, question, expected_answer))
    return triples


class TestByteFidelity:
    """The shipped JSONL is byte-identical to the vendored TSVs (R-1)."""

    def test_every_vendored_pair_is_byte_identical_in_shipped_set(self):
        vendored = _vendored_pairs()
        shipped = load_test_set(TEST_SET_PATH)
        shipped_by_question = {case.question: case for case in shipped}

        assert len(shipped) == len(vendored), (
            f"shipped set has {len(shipped)} cases, vendored TSVs have {len(vendored)}"
        )

        for category, question, expected_answer in vendored:
            assert question in shipped_by_question, f"missing question: {question!r}"
            case = shipped_by_question[question]
            assert case.expected_answer == expected_answer, (
                f"expected_answer mismatch for {question!r}:\n"
                f"  vendored: {expected_answer!r}\n"
                f"  shipped:  {case.expected_answer!r}"
            )
            assert case.category == category, (
                f"category mismatch for {question!r}: "
                f"vendored={category!r} shipped={case.category!r}"
            )

    def test_per_category_counts(self):
        shipped = load_test_set(TEST_SET_PATH)
        counts: dict[str, int] = {}
        for case in shipped:
            counts[case.category] = counts.get(case.category, 0) + 1

        assert counts.get("documentation") == 38
        assert counts.get("building-alkemio") == 8
        assert counts.get("design-thinker") == 25
        assert len(shipped) == 71

    def test_special_characters_are_literally_present(self):
        """Guards against silent NFKC normalization (U+2122 -> 'TM', etc.)."""
        raw = TEST_SET_PATH.read_text(encoding="utf-8")
        assert "—" in raw, "em dash (—) missing from shipped set"
        assert "…" in raw, "ellipsis (…) missing from shipped set"
        assert "™" in raw, "trademark sign (™) missing from shipped set"

    def test_all_questions_unique(self):
        shipped = load_test_set(TEST_SET_PATH)
        questions = [case.question for case in shipped]
        assert len(questions) == len(set(questions))


class TestAssertionsMatchShippedRule:
    """The shipped assertions are exactly what derive_assertions() produces now."""

    def test_derived_assertions_match_shipped_assertions_for_every_case(self):
        shipped = load_test_set(TEST_SET_PATH)
        assert shipped, "golden set must not be empty"
        for case in shipped:
            expected = derive_assertions(case.expected_answer)
            assert expected == case.assertions, (
                f"assertion drift for question={case.question!r}: "
                f"derived={expected!r} shipped={case.assertions!r}"
            )


class TestNoFabricatedFields:
    """The golden set carries no fabricated relevant_documents (FR-006)."""

    def test_no_case_carries_relevant_documents(self):
        shipped = load_test_set(TEST_SET_PATH)
        for case in shipped:
            assert case.relevant_documents == [], (
                f"question={case.question!r} unexpectedly carries "
                f"relevant_documents={case.relevant_documents!r}"
            )

    def test_loads_via_load_test_set(self):
        shipped = load_test_set(TEST_SET_PATH)
        assert len(shipped) == 71


class TestEvaluationsDirectoryIsEmpty:
    """spec-vc-5: evaluations/ holds only .gitkeep — a faked baseline run
    result can never be committed there unnoticed."""

    def test_evaluations_dir_contains_only_gitkeep(self):
        assert EVALUATIONS_DIR.is_dir()
        entries = sorted(p.name for p in EVALUATIONS_DIR.iterdir())
        assert entries == [".gitkeep"]
