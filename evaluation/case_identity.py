"""Public, versioned identity for inputs to an evaluation case."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

CASE_IDENTITY_VERSION = "evaluation-case-identity/v1"
CASE_IDENTITY_FIELDS = (
    "question",
    "expected_answer",
    "relevant_documents",
)


def _value(case: object, field: str) -> Any:
    if isinstance(case, Mapping):
        if field not in case:
            raise ValueError("Evaluation case identity is incomplete")
        return case[field]
    if not hasattr(case, field):
        raise ValueError("Evaluation case identity is incomplete")
    return getattr(case, field)


def evaluation_case_identity_payload(case: object) -> dict[str, object]:
    """Return the only payload allowed for v1 case identity.

    A ``TestCase`` schema extension must update this public contract instead of
    silently changing the producer's bytes while the persisted verifier keeps
    accepting its old hand-written projection.
    """
    model_fields = getattr(type(case), "model_fields", None)
    if model_fields is not None and set(model_fields) != set(CASE_IDENTITY_FIELDS):
        raise ValueError("Evaluation case identity schema is not declared for this version")
    return {
        "schema": CASE_IDENTITY_VERSION,
        "question": _value(case, "question"),
        "expected_answer": _value(case, "expected_answer"),
        "relevant_documents": _value(case, "relevant_documents"),
    }


def evaluation_case_identity_bytes(case: object) -> bytes:
    """Serialize v1 identity deterministically and without implementation data."""
    return json.dumps(
        evaluation_case_identity_payload(case),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def evaluation_case_digest(case: object) -> str:
    """Return the SHA-256 identity of a single validated evaluation input."""
    return hashlib.sha256(evaluation_case_identity_bytes(case)).hexdigest()


def ordered_evaluation_case_digest(cases: list[object]) -> str:
    """Hash ordered v1 case bytes, retaining dataset order as evidence."""
    payload = [evaluation_case_identity_payload(case) for case in cases]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
