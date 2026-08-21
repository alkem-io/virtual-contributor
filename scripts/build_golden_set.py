"""Build evaluation/golden/test_set.jsonl from the vendored operator TSVs.

Reads the three vendored source files under ``evaluation/golden/source/``,
derives a ``category`` from which file a row came from, derives assertions
by rule (never hand-annotated — see ``evaluation/assertions.py``), self-checks
every derived assertion against the answer it came from, and writes the
result wholesale to ``evaluation/golden/test_set.jsonl``.

Text is split on the first tab only and normalized with Unicode NFC — never
NFKC, which would rewrite U+2122 (TM) to the ASCII digraph "TM" and silently
alter the operator's exact wording.

Usage:
    poetry run python scripts/build_golden_set.py
"""

from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from evaluation.assertions import derive_assertions, evaluate_assertions  # noqa: E402
from evaluation.dataset import TestCase, write_test_cases  # noqa: E402

SOURCE_DIR = REPO_ROOT / "evaluation" / "golden" / "source"
OUTPUT_PATH = REPO_ROOT / "evaluation" / "golden" / "test_set.jsonl"

# (source filename, category, expected row count) — order matters: this is
# the order cases are written in.
SOURCES: tuple[tuple[str, str, int], ...] = (
    ("cat1-documentation.tsv", "documentation", 38),
    ("cat2-building-alkemio.tsv", "building-alkemio", 8),
    ("cat3-design-thinker.tsv", "design-thinker", 25),
)


def _nfc(text: str) -> str:
    """Unicode NFC normalization only — never NFKC (rewrites TM -> "TM")."""
    return unicodedata.normalize("NFC", text)


def _parse_tsv(path: Path, category: str) -> list[TestCase]:
    """Parse one vendored TSV: split on the first tab only, NFC-normalize."""
    cases: list[TestCase] = []
    raw_text = path.read_text(encoding="utf-8")
    lines = raw_text.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    for line_num, line in enumerate(lines, start=1):
        if not line:
            continue
        parts = line.split("\t", 1)
        if len(parts) != 2:
            raise ValueError(
                f"{path.name}:{line_num}: expected exactly 2 tab-separated "
                f"fields, got {len(parts)}"
            )
        question, expected_answer = parts
        question = _nfc(question)
        expected_answer = _nfc(expected_answer)
        if question != question.strip() or expected_answer != expected_answer.strip():
            raise ValueError(
                f"{path.name}:{line_num}: leading/trailing whitespace in a field"
            )
        assertions = derive_assertions(expected_answer)
        cases.append(
            TestCase(
                question=question,
                expected_answer=expected_answer,
                category=category,
                assertions=assertions,
            )
        )
    return cases


def _self_check(cases: list[TestCase]) -> None:
    """Verify every derived assertion passes against the answer it came from.

    Aborts the build (no file write) on any failure — an assertion its own
    reference answer cannot satisfy is definitionally broken (FR-013).
    """
    failures: list[str] = []
    for case in cases:
        if not case.assertions:
            continue
        outcome = evaluate_assertions(case.expected_answer, case.assertions)
        if outcome.status != "passed":
            failures.append(
                f"  question={case.question!r}\n"
                f"  expected_answer={case.expected_answer!r}\n"
                f"  assertions={case.assertions!r}\n"
                f"  missing={outcome.missing!r}"
            )
    if failures:
        print("Self-check FAILED — derived assertions do not hold against their own answers:", file=sys.stderr)
        for failure in failures:
            print(failure, file=sys.stderr)
        sys.exit(1)


def build() -> list[TestCase]:
    all_cases: list[TestCase] = []
    for filename, category, expected_count in SOURCES:
        path = SOURCE_DIR / filename
        cases = _parse_tsv(path, category)
        if len(cases) != expected_count:
            print(
                f"ERROR: {filename} produced {len(cases)} cases, expected {expected_count}",
                file=sys.stderr,
            )
            sys.exit(1)
        all_cases.extend(cases)

    questions = [c.question for c in all_cases]
    if len(questions) != len(set(questions)):
        seen: set[str] = set()
        dupes: list[str] = []
        for q in questions:
            if q in seen:
                dupes.append(q)
            seen.add(q)
        print(f"ERROR: duplicate question(s) across categories: {dupes}", file=sys.stderr)
        sys.exit(1)

    _self_check(all_cases)
    return all_cases


def main() -> None:
    cases = build()
    write_test_cases(cases, OUTPUT_PATH)
    with_assertions = sum(1 for c in cases if c.assertions)
    print(f"Wrote {len(cases)} cases to {OUTPUT_PATH}")
    print(f"{with_assertions} cases carry >=1 assertion")


if __name__ == "__main__":
    main()
