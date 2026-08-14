"""Shared fixtures for the per-plugin rewrite tests.

Not a test module — the three `test_*_rewrite.py` files import from here so the
anaphoric corpus is defined exactly once. If it lived in only one of them, the
other plugins could silently diverge from it.
"""

from __future__ import annotations

from tests.conftest import MockLLMPort

HISTORY = [
    {"role": "human", "content": "List the L1 spaces"},
    {"role": "assistant", "content": "There are two: Alpha and Beta."},
]

RESOLVED = "What are the L1 spaces in the Alkemio platform?"

#: Turns that are meaningless without the preceding one. **These must always be
#: rewritten.** The story recommends skipping "simple" queries; measured against
#: the shipped classifier, 9 of these 12 classify SIMPLE — so implementing that
#: recommendation literally sends unresolved fragments to the vector store.
ANAPHORIC = [
    "the name of the lead",
    "show me those",
    "and after that?",
    "can you list them?",
    "same for challenges?",
    "who is he?",
    "what about subspaces?",
    "and the second one?",
    "why is that",
    "tell me more",
    "which ones",
    "when did that happen",
]

#: Turns that are entirely small talk — safe to skip, because the classifier
#: requires the *whole* message to be conversational, so it cannot carry a
#: question needing resolution.
CONVERSATIONAL = ["thanks!", "ok", "thank you", "great", "cheers"]


class CountingLLM(MockLLMPort):
    """Counts invocations; the first one answers as a condense would."""

    def __init__(self, response: str = "an answer") -> None:
        super().__init__(response=response)
        self.n = 0

    async def invoke(self, messages, **kw):  # type: ignore[override]
        self.n += 1
        return RESOLVED if self.n == 1 else "an answer"


class SkipConversational:
    """Stands in for the unmerged classifier: skips only small talk."""

    def should_skip_rewrite(self, message: str) -> bool:
        return message.strip().lower() in {c.lower() for c in CONVERSATIONAL}


class SkipEverySimpleQuery:
    """The policy the story literally recommends — kept to prove it is wrong.

    Approximates "skip anything short and unpunctuated", which is what a
    SIMPLE-skipping gate does to these turns.
    """

    def should_skip_rewrite(self, message: str) -> bool:
        return len(message.split()) <= 6
