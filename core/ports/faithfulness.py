"""Port for judging whether an answer is supportable by what was retrieved.

The failure this addresses is a model stating something confidently that
nothing in the knowledge base backs. That is at its worst when retrieval came
back empty: there was no evidence at all, and the answer is whatever the model
already believed.

**Synchronous on purpose.** An ``async`` signature would invite a future
implementer to put a network call behind it — an LLM judge, most likely — and
this port exists to be the cheap, local, always-on check. A judge is a
different thing with a different cost profile; if one is ever accepted it
belongs on its own asynchronous port, not smuggled in behind this one.

Primitives only: no store, no LLM, no repo type appears here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class FaithfulnessVerdict:
    """Whether an answer is supportable, and why.

    ``reason`` is a stable machine-readable token so a log or metric can be
    aggregated on it; ``detail`` is for a human reading a single record.
    """

    supported: bool
    reason: str
    detail: str


@runtime_checkable
class FaithfulnessValidatorPort(Protocol):
    """Judges one answer against the context it was generated from."""

    def validate(self, *, answer: str, context: str) -> FaithfulnessVerdict:
        """Return a verdict for ``answer`` given ``context``.

        Must never raise and never perform I/O. Callers treat a verdict as an
        observation about an answer that has already been produced — it never
        changes, delays, or blocks what the member receives.
        """
        ...
