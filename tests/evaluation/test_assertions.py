"""Tests for evaluation/assertions.py — the deterministic exact-match layer.

Covers derivation (literal + enumeration patterns), evaluation (normalization,
missing-fact reporting, not_applicable), and the module's hard constraint of
zero model/socket/credential imports (FR-014).
"""

from __future__ import annotations

import sys

from evaluation.assertions import (
    Assertion,
    derive_assertions,
    evaluate_assertions,
)


# ---------------------------------------------------------------------------
# derive_assertions — literal patterns
# ---------------------------------------------------------------------------


def test_derives_email_as_contains():
    assertions = derive_assertions("Contact us at support@alkem.io for help.")
    assert assertions == [Assertion(kind="contains", values=["support@alkem.io"])]


def test_derives_bare_domain_as_contains_and_masks_email_domain():
    """The domain in an email must not be re-matched as a second anchor."""
    assertions = derive_assertions("Email support@alkem.io or visit interaction-design.org.")
    assert len(assertions) == 1
    assert assertions[0].kind == "contains"
    assert set(assertions[0].values) == {"support@alkem.io", "interaction-design.org"}


def test_derives_quoted_phrase_as_contains():
    assertions = derive_assertions('Click "Explore Spaces" from the menu.')
    assert assertions == [Assertion(kind="contains", values=["Explore Spaces"])]


def test_derives_licence_identifier_as_contains():
    assertions = derive_assertions("Alkemio is licensed under EUPL v1.2.")
    assert assertions == [Assertion(kind="contains", values=["EUPL v1.2"])]


def test_no_literal_anchor_yields_no_contains_assertion():
    assertions = derive_assertions("A collaboration platform for communities.")
    assert assertions == []


# ---------------------------------------------------------------------------
# derive_assertions — enumeration pattern (contains_all)
# ---------------------------------------------------------------------------


def test_derives_whole_answer_enumeration_as_contains_all():
    assertions = derive_assertions("Empathize, Define, Ideate, Prototype, Test.")
    assert assertions == [
        Assertion(
            kind="contains_all",
            values=["Empathize", "Define", "Ideate", "Prototype", "Test"],
        )
    ]


def test_enumeration_split_is_paren_aware():
    """A parenthetical containing a comma must stay one item, not be split."""
    answer = "Admin (manages settings, membership), Member, Guest."
    assertions = derive_assertions(answer)
    assert len(assertions) == 1
    assert assertions[0].kind == "contains_all"
    assert "Admin (manages settings, membership)" in assertions[0].values


def test_enumeration_drops_leading_conjunction_on_last_item():
    assertions = derive_assertions("Whiteboards, posts, memos, and events.")
    assert assertions == [
        Assertion(kind="contains_all", values=["Whiteboards", "posts", "memos", "events"])
    ]


def test_enumeration_requires_at_least_three_items():
    assertions = derive_assertions("Whiteboards and posts.")
    assert assertions == []


def test_enumeration_rejects_long_items():
    """An item over four words is a sentence fragment, not a checkable list item."""
    answer = "A non-linear iterative process to understand users, define needs, and ideate."
    assertions = derive_assertions(answer)
    assert not any(a.kind == "contains_all" for a in assertions)


def test_enumeration_rejects_leading_stopword():
    """'while embracing ambiguity' style fragments must not become list items."""
    answer = "While iterating, prototyping, testing, and refining."
    assertions = derive_assertions(answer)
    assert not any(a.kind == "contains_all" for a in assertions)


def test_enumeration_requires_trailing_period():
    assertions = derive_assertions("Whiteboards, posts, memos")
    assert assertions == []


# ---------------------------------------------------------------------------
# evaluate_assertions
# ---------------------------------------------------------------------------


def test_all_facts_present_passes():
    assertions = [Assertion(kind="contains", values=["support@alkem.io"])]
    outcome = evaluate_assertions("Email support@alkem.io for help.", assertions)
    assert outcome.status == "passed"
    assert outcome.missing == []


def test_one_missing_fact_fails_and_names_it():
    assertions = [Assertion(kind="contains", values=["support@alkem.io", "EUPL v1.2"])]
    outcome = evaluate_assertions("Email support@alkem.io for help.", assertions)
    assert outcome.status == "failed"
    assert outcome.missing == ["EUPL v1.2"]


def test_contains_all_reports_every_missing_item():
    assertions = [Assertion(kind="contains_all", values=["Empathize", "Define", "Ideate"])]
    outcome = evaluate_assertions("The process starts with Empathize.", assertions)
    assert outcome.status == "failed"
    assert set(outcome.missing) == {"Define", "Ideate"}


def test_no_assertions_is_not_applicable():
    outcome = evaluate_assertions("Any answer at all.", [])
    assert outcome.status == "not_applicable"
    assert outcome.missing == []


def test_evaluation_is_case_insensitive():
    assertions = [Assertion(kind="contains", values=["EUPL v1.2"])]
    outcome = evaluate_assertions("Licensed under eupl V1.2 terms.", assertions)
    assert outcome.status == "passed"


def test_evaluation_collapses_whitespace():
    assertions = [Assertion(kind="contains", values=["Explore Spaces"])]
    outcome = evaluate_assertions('Click "Explore   Spaces"  from the  menu.', assertions)
    assert outcome.status == "passed"


def test_paren_aware_item_matches_verbatim_in_pipeline_answer():
    assertions = [
        Assertion(kind="contains_all", values=["Admin (manages settings, membership)", "Member"])
    ]
    outcome = evaluate_assertions(
        "Roles include Admin (manages settings, membership) and Member.", assertions
    )
    assert outcome.status == "passed"


# ---------------------------------------------------------------------------
# FR-014 — no model client, socket, or credential dependency
# ---------------------------------------------------------------------------


def test_module_imports_and_evaluates_with_no_credentials_configured():
    """The module must work standing alone: import it fresh and evaluate,
    with nothing resembling a config or environment lookup in the process."""
    import importlib

    import evaluation.assertions as assertions_module

    reloaded = importlib.reload(assertions_module)
    outcome = reloaded.evaluate_assertions(
        "support@alkem.io",
        [reloaded.Assertion(kind="contains", values=["support@alkem.io"])],
    )
    assert outcome.status == "passed"


def test_module_does_not_import_network_or_credential_modules():
    forbidden_substrings = ("socket", "requests", "httpx", "openai", "langchain", "ragas")
    module_name = "evaluation.assertions"
    assert module_name in sys.modules
    module = sys.modules[module_name]
    source_path = module.__file__
    assert source_path is not None
    source = open(source_path, encoding="utf-8").read()
    import_lines = [
        line.strip() for line in source.splitlines()
        if line.strip().startswith("import ") or line.strip().startswith("from ")
    ]
    for line in import_lines:
        for forbidden in forbidden_substrings:
            assert forbidden not in line, f"assertions.py must not import {forbidden!r}: {line!r}"
