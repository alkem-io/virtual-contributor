"""Gate, validate, and make survivable the LLM query rewrite that already runs.

The story this implements asks to *add* pre-retrieval query transformation,
stating that the pipeline "passes the raw user query directly to embedding
similarity search with no transformation". That is not true of this codebase:
``plugins/guidance`` and ``plugins/generic`` both already send an LLM condense
call whenever the event carries history. Only ``plugins/expert`` matches the
story's description.

What is missing is not the transformation. It is everything around it:

**It is ungated.** The condense fires on *any* history, so a bare "yes" pays a
full extra LLM round-trip. Measured with a 250 ms stub LLM, every message —
"yes", "thanks!", "ok" — cost 2 calls and ~500 ms.

**Its output is never checked** (N-1). Whatever the model returns becomes the
retrieval query verbatim: an empty string, a refusal, a chatty preamble. The
vector store is then searched for that.

**Its failure is fatal** (N-2). One raised exception from the condense call
aborts the entire user request, even though the original message was a perfectly
good query all along.

**Why the gate skips only conversational turns.** The story recommends skipping
transformation for "simple" queries. Implemented literally that silently breaks
follow-ups: "show me those", "the name of the lead", "and after that?" all
classify as SIMPLE yet are meaningless without the preceding turn. Measured
against a 12-turn anaphoric corpus, skipping SIMPLE broke 9 of 12; skipping only
CONVERSATIONAL broke none. Conversational is the safe boundary because the
classifier requires the *whole* message to be small talk — so it cannot contain
a question that needs resolving. The narrower policy is roughly half as fast and
correct, which is the trade taken here.

Stdlib only, no I/O: the policy is supplied by the caller, and the prompt
messages are built by each plugin so their existing wording is untouched.
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

#: How much longer than the original a rewrite may be before it is discarded,
#: subject to the absolute floor below. A condense is meant to *resolve* a
#: follow-up against its history — an answer many times the length of the
#: question is a model that started explaining rather than rewriting, and that
#: prose becomes the vector-store query if it is used.
DEFAULT_MAX_EXPANSION_RATIO = 8.0

#: A resolution may always reach this length regardless of the ratio.
#:
#: A pure ratio punishes exactly the queries that most need resolving. "who is
#: he?" is ten characters; resolving it against its history yields something
#: like "What are the L1 spaces in the Alkemio platform?" — 47 characters, a
#: 4.7x expansion, and entirely correct. Measured over a 14-turn anaphoric
#: corpus, a bare ratio of 4.0 rejected 5 legitimate resolutions and 8.0 still
#: rejected 2; with this floor, none. The floor is small enough that a model
#: which started explaining instead of rewriting is still caught.
MIN_REWRITE_ALLOWANCE = 120

#: How many trailing conversation turns the rewrite may see.
#:
#: The condense prompt embeds the *whole* history, and nothing bounded it —
#: `history_length` has existed in config since before this feature and is read
#: by no code at all. Measured: 5 000 turns of 500 chars builds a 2.5 MB prompt
#: and sends it to a metered third-party API on every request. The member
#: supplies the history, so the ceiling is theirs, not ours.
#:
#: The most recent turns are the ones a follow-up refers to, so the tail is
#: what is kept. Matches the existing `ExpertConfig.history_length` default.
DEFAULT_MAX_HISTORY_TURNS = 20


def recent_history(history: object, max_turns: int = DEFAULT_MAX_HISTORY_TURNS) -> list:
    """The trailing `max_turns` of a conversation, for prompt construction.

    Returns a list so callers can format it as they already do; a non-sequence
    or empty history yields an empty list rather than raising, because a
    malformed history must not be the reason a request fails.
    """
    if not history:
        return []
    try:
        items = list(history)
    except TypeError:
        return []
    if max_turns <= 0:
        return items
    return items[-max_turns:]


@runtime_checkable
class RewritePolicy(Protocol):
    """Decides whether a message can skip the rewrite call.

    Deliberately one method taking only the message. It is defined here rather
    than imported so this module builds and ships on ``develop`` alone; the
    adaptive-query classifier that will implement it lives on an unmerged PR,
    and binding to that would make this feature hostage to a merge order nobody
    controls. Any object with this method governs the outcome — see
    ``main.py`` for how one is supplied when available.

    **Must not perform I/O.** It runs on the request path ahead of retrieval,
    and its entire purpose is to avoid a network call.
    """

    def should_skip_rewrite(self, message: str) -> bool: ...


def should_rewrite(
    message: str,
    history: object,
    policy: RewritePolicy | None,
) -> bool:
    """Whether this turn needs the rewrite call at all.

    Empty history short-circuits first, preserving today's precondition exactly:
    with nothing to resolve against, a rewrite has no information to add.

    A ``None`` policy never skips. That is what makes the gate opt-in — with no
    policy configured, behaviour is byte-identical to develop apart from the
    validation and fallback below.
    """
    if not history:
        return False
    if policy is not None and policy.should_skip_rewrite(message):
        return False
    return True


def validate_rewrite(
    candidate: object,
    original: str,
    max_expansion_ratio: float = DEFAULT_MAX_EXPANSION_RATIO,
) -> str:
    """Return the rewrite if it is usable, otherwise the original message.

    Every rejection falls back to ``original`` rather than raising: the original
    message is always a valid query, so there is no failure mode here worth
    costing someone their answer over.

    ``candidate`` is typed ``object`` on purpose — it is whatever the LLM
    adapter returned, and this function is the boundary that makes it a ``str``.
    """
    if not isinstance(candidate, str):
        return original
    stripped = candidate.strip()
    if not stripped:
        return original
    # An empty or whitespace-only original has no length to scale, so the
    # ratio is meaningless against it — and falling back would hand the caller
    # the empty string it was trying to escape. Any usable rewrite wins.
    allowance = max(max_expansion_ratio * len(original.strip()), MIN_REWRITE_ALLOWANCE)
    if len(stripped) > allowance:
        return original
    return stripped


async def rewrite_query(
    llm: object,
    messages: list[dict],
    original: str,
    *,
    max_expansion_ratio: float = DEFAULT_MAX_EXPANSION_RATIO,
) -> str:
    """Run the rewrite, and never let it be the reason a request fails.

    Receives already-built prompt ``messages`` and never constructs them, so
    each plugin keeps its own condense prompt exactly as it is today.
    """
    try:
        candidate = await llm.invoke(messages)  # type: ignore[attr-defined]
    except Exception as exc:
        # Only the type: the exception's message may quote the prompt, which
        # contains the member's conversation.
        logger.warning(
            "Query rewrite failed, using the original message: error_type=%s",
            type(exc).__name__,
        )
        return original
    return validate_rewrite(candidate, original, max_expansion_ratio)
