"""Conformance tests for the shared retrieved-context format contract."""

from __future__ import annotations

import pytest

from core.domain.prompts_shared import (
    CITATION_INSTRUCTIONS,
    EMPTY_CONTEXT_DECLINE_INSTRUCTIONS,
    EMPTY_CONTEXT_SENTINEL,
    join_document_blocks,
    render_document_block,
)


def test_document_blocks_are_dense_one_based_and_visually_separated() -> None:
    context = join_document_blocks(
        [
            render_document_block(1, "first passage", {"title": "One"}),
            render_document_block(2, "second passage", {"title": "Two"}),
            render_document_block(3, "third passage", {"title": "Three"}),
        ]
    )

    assert "[Document 1 · One]" in context
    assert "[Document 2 · Two]" in context
    assert "[Document 3 · Three]" in context
    assert "first passage\n\n[Document 2" in context


@pytest.mark.parametrize(
    ("metadata", "identity"),
    [
        (
            {"title": "", "uri": "https://example.test/one", "source": "source-a"},
            "https://example.test/one",
        ),
        ({"title": "", "source": "source-b"}, "source-b"),
        ({"title": ""}, "Untitled"),
    ],
)
def test_document_identity_falls_back_without_fabricating_hierarchy(
    metadata: dict[str, object], identity: str
) -> None:
    block = render_document_block(1, "passage", metadata)

    assert identity in block
    assert ">" not in block


def test_document_label_includes_available_kind_and_origin() -> None:
    block = render_document_block(
        1,
        "passage",
        {
            "title": "Welcome",
            "type": "callout",
            "uri": "https://welcome.alkem.io",
            "source": "legacy-source",
        },
    )

    assert "[Document 1 · Welcome · callout · origin: https://welcome.alkem.io]" in block


def test_passage_content_is_verbatim() -> None:
    content = "  exact content\nwith punctuation & spacing  "

    block = render_document_block(1, content, {"title": "A title"})

    assert block.endswith(content)


def test_citation_instruction_uses_the_same_document_number_scheme() -> None:
    block = render_document_block(1, "passage", {"title": "One"})

    assert "[Document 1" in block
    assert "[Document N]" in CITATION_INSTRUCTIONS
    assert "appear in the supplied context" in CITATION_INSTRUCTIONS


def test_empty_context_has_a_sentinel_and_decline_instruction() -> None:
    assert join_document_blocks([]) == EMPTY_CONTEXT_SENTINEL
    assert EMPTY_CONTEXT_SENTINEL in EMPTY_CONTEXT_DECLINE_INSTRUCTIONS
    assert "do not have information" in EMPTY_CONTEXT_DECLINE_INSTRUCTIONS
