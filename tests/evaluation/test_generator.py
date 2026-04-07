"""Tests for evaluation/generator.py — synthetic test pair generation."""

from __future__ import annotations

from pathlib import Path


from evaluation.dataset import TestCase, load_test_set


class TestSyntheticGenerator:
    async def test_generates_valid_jsonl(self, tmp_path: Path):
        """Generated output should be loadable by load_test_set."""
        from evaluation.generator import _write_synthetic_cases

        cases = [
            TestCase(question="Q1?", expected_answer="A1", relevant_documents=["doc1"]),
            TestCase(question="Q2?", expected_answer="A2", relevant_documents=["doc2"]),
        ]
        output = tmp_path / "synthetic.jsonl"
        _write_synthetic_cases(cases, output)

        loaded = load_test_set(output)
        assert len(loaded) == 2
        assert loaded[0].question == "Q1?"

    async def test_output_format_matches_test_case(self, tmp_path: Path):
        """Each generated case must have question, expected_answer, relevant_documents."""
        from evaluation.generator import _write_synthetic_cases

        cases = [
            TestCase(
                question="What is X?",
                expected_answer="X is Y",
                relevant_documents=["https://example.com/x"],
            ),
        ]
        output = tmp_path / "out.jsonl"
        _write_synthetic_cases(cases, output)

        loaded = load_test_set(output)
        assert loaded[0].question == "What is X?"
        assert loaded[0].expected_answer == "X is Y"
        assert loaded[0].relevant_documents == ["https://example.com/x"]
