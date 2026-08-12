"""Shared retrieved-context rendering and grounding prompt instructions.

Both retrieval-backed answering paths consume this module.  Keeping document
labels and citation instructions together prevents the two numbering schemes
from drifting while leaving the platform-facing response envelope untouched.
"""

from __future__ import annotations

from enum import Enum
from typing import Mapping, Sequence


# Retain the established wording while making it a shared, explicit sentinel
# for both retrieval-backed paths.
EMPTY_CONTEXT_SENTINEL = "No relevant context found."

GROUNDING_INSTRUCTIONS = """Grounding requirements:
- Answer only from the supplied context.
- Do not use outside knowledge or fill gaps with plausible information.
- State plainly which part of the question the supplied context does not cover.
- Never present an unsupported statement as fact."""

EMPTY_CONTEXT_DECLINE_INSTRUCTIONS = f"""When the context is exactly
{EMPTY_CONTEXT_SENTINEL}
state plainly that you do not have information on the topic. Do not answer
from general knowledge and do not cite a document."""

CITATION_INSTRUCTIONS = """For every substantive claim, cite the supporting
document inline using its [Document N] label. Cite only document numbers that
appear in the supplied context; never cite a number that was not supplied."""

STEP_BY_STEP_ANSWER_INSTRUCTIONS = """This is a complex question. Work through
each part privately before responding, then provide a complete finished answer
that addresses every part. Do not reveal intermediate reasoning, scratch work,
or chain-of-thought in the reply."""


def _metadata_text(metadata: Mapping[str, object], key: str) -> str:
    """Return a present metadata value without inventing a replacement."""

    value = metadata.get(key)
    if value is None:
        return ""
    if isinstance(value, Enum):
        value = value.value
    text = str(value).strip()
    return "" if text.casefold() == "none" else text


def render_document_block(
    number: int, content: str, metadata: Mapping[str, object] | None = None
) -> str:
    """Render one retrieved passage as a labelled, verbatim document block.

    Labels use only existing metadata.  The human-readable identity falls back
    from title to URI to source to ``Untitled``; no hierarchy is synthesized.
    """

    if number < 1:
        raise ValueError("Document numbers must be 1-based")

    metadata = metadata or {}
    title = _metadata_text(metadata, "title")
    uri = _metadata_text(metadata, "uri")
    source = _metadata_text(metadata, "source")
    kind = _metadata_text(metadata, "type")
    origin = uri or source
    identity = title or uri or source or "Untitled"

    label_parts = [f"Document {number}", identity]
    if kind:
        label_parts.append(kind)
    if origin:
        label_parts.append(f"origin: {origin}")
    return f"[{' · '.join(label_parts)}]\n{content}"


def join_document_blocks(blocks: Sequence[str]) -> str:
    """Join rendered blocks, or use the explicit no-material sentinel."""

    return "\n\n".join(blocks) if blocks else EMPTY_CONTEXT_SENTINEL
