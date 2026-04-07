"""Tests for evaluation/dataset.py — JSONL loading, validation, duplicate detection."""

from __future__ import annotations

from pathlib import Path

import pytest

from evaluation.dataset import TestCase, load_test_set, validate_test_set, write_test_cases


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

    def test_empty_documents_rejected(self):
        with pytest.raises(Exception):
            TestCase(question="q", expected_answer="a", relevant_documents=[])


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
