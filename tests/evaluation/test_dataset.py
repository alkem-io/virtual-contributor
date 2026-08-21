"""Tests for evaluation/dataset.py — JSONL loading, validation, duplicate detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from evaluation.dataset import (
    TestCase,
    canonical_test_set_digest,
    filter_by_category,
    load_test_set,
    validate_test_set,
    write_test_cases,
)
from evaluation.case_identity import CASE_IDENTITY_VERSION, evaluation_case_identity_payload


# ---------------------------------------------------------------------------
# TestCase model validation
# ---------------------------------------------------------------------------


class TestTestCaseModel:
    def test_valid_case(self):
        case = TestCase(
            question="What is Alkemio?",
            expected_answer="A collaboration platform.",
            relevant_documents=["https://alkem.io/about"],
        )
        assert case.question == "What is Alkemio?"

    def test_empty_question_rejected(self):
        with pytest.raises(Exception):
            TestCase(question="", expected_answer="answer", relevant_documents=["doc"])

    def test_empty_answer_rejected(self):
        with pytest.raises(Exception):
            TestCase(question="q", expected_answer="", relevant_documents=["doc"])

    def test_empty_documents_accepted(self):
        """relevant_documents is optional (FR-006): an empty list is now valid,
        not fabricated. The new golden set carries no reference documents at all."""
        case = TestCase(question="q", expected_answer="a")
        assert case.relevant_documents == []

    def test_relevant_documents_still_loads_when_supplied(self):
        """Backward compatibility (FR-010, risk R-5): generator.py still writes
        this shape and it must still load."""
        case = TestCase(question="q", expected_answer="a", relevant_documents=["https://alkem.io/x"])
        assert case.relevant_documents == ["https://alkem.io/x"]

    def test_category_and_assertions_default_absent(self):
        case = TestCase(question="q", expected_answer="a")
        assert case.category is None
        assert case.assertions == []

    def test_unknown_category_rejected(self):
        with pytest.raises(Exception):
            TestCase(question="q", expected_answer="a", category="not-a-real-category")


def test_ordered_test_set_digest_is_path_independent_and_content_stable():
    first = [TestCase(question="Q", expected_answer="A", relevant_documents=["d"])]
    # Independently constructed, equal content — not the same objects.
    second = [TestCase(question="Q", expected_answer="A", relevant_documents=["d"])]
    assert canonical_test_set_digest(first) == canonical_test_set_digest(second)


def test_ordered_test_set_digest_changes_for_reorder_or_field_change():
    first = TestCase(question="Q1", expected_answer="A", relevant_documents=["d"])
    second = TestCase(question="Q2", expected_answer="A", relevant_documents=["d"])
    assert canonical_test_set_digest([first, second]) != canonical_test_set_digest([second, first])


def test_case_identity_v1_is_shared_and_versioned():
    # TestCase now carries category/assertions in addition to the v1 identity
    # fields, so dataset.py projects onto the declared identity fields before
    # calling into case_identity — direct evaluation_case_identity_payload(case)
    # is expected to reject the wider schema (see
    # test_wider_test_case_schema_is_projected_before_identity below).
    payload = {"question": "Q", "expected_answer": "A", "relevant_documents": ["d"]}
    assert evaluation_case_identity_payload(payload)["schema"] == CASE_IDENTITY_VERSION
    case = TestCase(question="Q", expected_answer="A", relevant_documents=["d"])
    assert canonical_test_set_digest([case])


def test_wider_test_case_schema_is_projected_before_identity():
    """A TestCase with category/assertions set still hashes: dataset.py's
    _identity_payload projects it onto exactly the v1 identity fields first."""
    case = TestCase(
        question="Q", expected_answer="A", relevant_documents=["d"],
        category="documentation",
    )
    with pytest.raises(ValueError, match="schema"):
        evaluation_case_identity_payload(case)
    assert canonical_test_set_digest([case])


def test_case_identity_v1_changes_for_each_declared_field():
    base = TestCase(question="Q", expected_answer="A", relevant_documents=["d"])
    assert canonical_test_set_digest([base]) != canonical_test_set_digest([TestCase(question="R", expected_answer="A", relevant_documents=["d"])])
    assert canonical_test_set_digest([base]) != canonical_test_set_digest([TestCase(question="Q", expected_answer="B", relevant_documents=["d"])])
    assert canonical_test_set_digest([base]) != canonical_test_set_digest([TestCase(question="Q", expected_answer="A", relevant_documents=["e"])])


# ---------------------------------------------------------------------------
# load_test_set
# ---------------------------------------------------------------------------


class TestLoadTestSet:
    def test_loads_valid_jsonl(self, tmp_path: Path):
        p = tmp_path / "test.jsonl"
        p.write_text(
            '{"question": "Q1", "expected_answer": "A1", "relevant_documents": ["d1"]}\n'
            '{"question": "Q2", "expected_answer": "A2", "relevant_documents": ["d2"]}\n'
        )
        cases = load_test_set(p)
        assert len(cases) == 2
        assert cases[0].question == "Q1"

    def test_file_not_found(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_test_set(tmp_path / "missing.jsonl")

    def test_invalid_json_raises(self, tmp_path: Path):
        p = tmp_path / "bad.jsonl"
        p.write_text("not json\n")
        with pytest.raises(ValueError, match="validation errors"):
            load_test_set(p)

    def test_empty_file_raises(self, tmp_path: Path):
        p = tmp_path / "empty.jsonl"
        p.write_text("")
        with pytest.raises(ValueError, match="empty"):
            load_test_set(p)

    def test_skips_blank_lines(self, tmp_path: Path):
        p = tmp_path / "blanks.jsonl"
        p.write_text(
            '{"question": "Q1", "expected_answer": "A1", "relevant_documents": ["d1"]}\n'
            "\n"
            '{"question": "Q2", "expected_answer": "A2", "relevant_documents": ["d2"]}\n'
        )
        cases = load_test_set(p)
        assert len(cases) == 2

    def test_duplicate_questions_logged(self, tmp_path: Path, caplog):
        p = tmp_path / "dup.jsonl"
        p.write_text(
            '{"question": "Same", "expected_answer": "A1", "relevant_documents": ["d1"]}\n'
            '{"question": "Same", "expected_answer": "A2", "relevant_documents": ["d2"]}\n'
        )
        cases = load_test_set(p)
        assert len(cases) == 2
        assert "Duplicate" in caplog.text


# ---------------------------------------------------------------------------
# validate_test_set
# ---------------------------------------------------------------------------


class TestValidateTestSet:
    def test_valid_returns_empty(self, tmp_path: Path):
        p = tmp_path / "ok.jsonl"
        p.write_text('{"question": "Q", "expected_answer": "A", "relevant_documents": ["d"]}\n')
        assert validate_test_set(p) == []

    def test_missing_file(self, tmp_path: Path):
        issues = validate_test_set(tmp_path / "nope.jsonl")
        assert len(issues) == 1
        assert "not found" in issues[0]

    def test_reports_duplicates(self, tmp_path: Path):
        p = tmp_path / "dup.jsonl"
        p.write_text(
            '{"question": "Same", "expected_answer": "A1", "relevant_documents": ["d1"]}\n'
            '{"question": "Same", "expected_answer": "A2", "relevant_documents": ["d2"]}\n'
        )
        issues = validate_test_set(p)
        assert any("duplicate" in i for i in issues)


# ---------------------------------------------------------------------------
# write_test_cases
# ---------------------------------------------------------------------------


class TestWriteTestCases:
    def test_round_trip(self, tmp_path: Path):
        cases = [
            TestCase(question="Q1", expected_answer="A1", relevant_documents=["d1"]),
            TestCase(question="Q2", expected_answer="A2", relevant_documents=["d2"]),
        ]
        p = tmp_path / "out.jsonl"
        write_test_cases(cases, p)
        loaded = load_test_set(p)
        assert len(loaded) == 2
        assert loaded[0].question == "Q1"
        assert loaded[1].expected_answer == "A2"

    def test_creates_parent_dirs(self, tmp_path: Path):
        p = tmp_path / "sub" / "dir" / "out.jsonl"
        write_test_cases(
            [TestCase(question="Q", expected_answer="A", relevant_documents=["d"])],
            p,
        )
        assert p.exists()

    def test_bare_case_emits_only_question_and_expected_answer(self, tmp_path: Path):
        """exclude_defaults=True (T003): a case with no documents/category/
        assertions must not emit those keys at all."""
        import json

        p = tmp_path / "out.jsonl"
        write_test_cases([TestCase(question="Q", expected_answer="A")], p)
        line = p.read_text().strip()
        assert json.loads(line) == {"question": "Q", "expected_answer": "A"}


# ---------------------------------------------------------------------------
# filter_by_category — the mechanism behind --category
# ---------------------------------------------------------------------------


class TestFilterByCategory:
    def _cases(self) -> list[TestCase]:
        return [
            TestCase(question="Q1", expected_answer="A1", category="documentation"),
            TestCase(question="Q2", expected_answer="A2", category="building-alkemio"),
            TestCase(question="Q3", expected_answer="A3", category="design-thinker"),
            TestCase(question="Q4", expected_answer="A4", category="documentation"),
            TestCase(question="Q5", expected_answer="A5"),  # untagged, e.g. synthetic
        ]

    def test_selects_only_the_requested_category(self):
        result = filter_by_category(self._cases(), "documentation")
        assert [c.question for c in result] == ["Q1", "Q4"]

    def test_each_category_selects_its_own_count(self):
        cases = self._cases()
        assert len(filter_by_category(cases, "documentation")) == 2
        assert len(filter_by_category(cases, "building-alkemio")) == 1
        assert len(filter_by_category(cases, "design-thinker")) == 1

    def test_untagged_case_never_matches_a_specific_filter(self):
        result = filter_by_category(self._cases(), "documentation")
        assert "Q5" not in [c.question for c in result]

    def test_no_matching_cases_returns_empty_list(self):
        cases = [TestCase(question="Q1", expected_answer="A1", category="documentation")]
        assert filter_by_category(cases, "design-thinker") == []
