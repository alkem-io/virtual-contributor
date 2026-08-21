"""Golden test set I/O: JSONL load, validate, and write."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from evaluation.assertions import Assertion
from evaluation.case_identity import evaluation_case_digest, ordered_evaluation_case_digest

logger = logging.getLogger(__name__)

DEFAULT_TEST_SET_PATH = Path("evaluation/golden/test_set.jsonl")

Category = Literal["documentation", "building-alkemio", "design-thinker"]


class TestCase(BaseModel):
    """A single evaluation unit from the golden test set."""

    question: str = Field(min_length=1)
    expected_answer: str = Field(min_length=1)
    relevant_documents: list[str] = Field(default_factory=list)
    category: Category | None = None
    assertions: list[Assertion] = Field(default_factory=list)


def _identity_payload(case: TestCase) -> dict[str, object]:
    """Project a case onto exactly the v1 case-identity fields.

    ``category`` and ``assertions`` are metadata about a case, not inputs a
    RAGAS score is computed from, so they are deliberately excluded from the
    identity that pairs runs for comparison. Passing the projection (not the
    ``TestCase`` object itself) keeps identity stable as the schema widens —
    the same pattern already used by ``report.py``'s digest helpers.
    """
    return {
        "question": case.question,
        "expected_answer": case.expected_answer,
        "relevant_documents": case.relevant_documents,
    }


def canonical_test_set_digest(cases: list[TestCase]) -> str:
    """Hash ordered canonical case JSON, independent of its source path."""
    return ordered_evaluation_case_digest([_identity_payload(case) for case in cases])


def successful_case_digest(case: TestCase) -> str:
    """Stable identity for the successful input case, excluding model output."""
    return evaluation_case_digest(_identity_payload(case))


def load_test_set(path: Path = DEFAULT_TEST_SET_PATH) -> list[TestCase]:
    """Load and validate test cases from a JSONL file.

    Raises FileNotFoundError if the file does not exist.
    Raises ValueError on validation errors or duplicate questions.
    """
    if not path.exists():
        raise FileNotFoundError(f"Test set not found: {path}")

    cases: list[TestCase] = []
    seen_questions: set[str] = set()
    errors: list[str] = []

    with path.open() as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                case = TestCase.model_validate(data)
            except (json.JSONDecodeError, Exception) as exc:
                errors.append(f"Line {line_num}: {exc}")
                continue

            if case.question in seen_questions:
                logger.warning("Duplicate question on line %d: %s", line_num, case.question[:60])
            seen_questions.add(case.question)
            cases.append(case)

    if errors:
        raise ValueError("Test set validation errors:\n" + "\n".join(errors))

    if not cases:
        raise ValueError(f"Test set is empty: {path}")

    logger.info("Loaded %d test cases from %s", len(cases), path)
    return cases


def validate_test_set(path: Path = DEFAULT_TEST_SET_PATH) -> list[str]:
    """Validate a test set file and return a list of issues (empty = valid)."""
    issues: list[str] = []

    if not path.exists():
        return [f"File not found: {path}"]

    seen_questions: set[str] = set()

    with path.open() as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                TestCase.model_validate(data)
            except json.JSONDecodeError as exc:
                issues.append(f"Line {line_num}: invalid JSON — {exc}")
            except Exception as exc:
                issues.append(f"Line {line_num}: validation error — {exc}")
            else:
                q = data.get("question", "")
                if q in seen_questions:
                    issues.append(f"Line {line_num}: duplicate question — {q[:60]}")
                seen_questions.add(q)

    return issues


def write_test_cases(cases: list[TestCase], path: Path) -> None:
    """Write test cases to a JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for case in cases:
            f.write(case.model_dump_json(exclude_defaults=True) + "\n")
    logger.info("Wrote %d test cases to %s", len(cases), path)
