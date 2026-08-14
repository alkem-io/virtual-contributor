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
        """Judge one answer against the context it was generated from.

        **Synchronous on purpose, and that is a constraint on implementers,
        not a convenience.** This is called from the plugin's async handler, so
        the call occupies the event loop for its whole duration — an
        implementation that blocks blocks every other message this worker is
        serving, not just this one. Anything needing a model or a network call
        does not belong behind this signature; it belongs in an out-of-band
        path. An async signature here would have invited exactly that.

        Concretely: a citation verifier is a string check against the context
        and fits here directly. An LLM judge does not — it belongs out of band,
        with this port used to record the verdict rather than to fetch it.
        """
        """Return a verdict for ``answer`` given ``context``.

        Must never raise and never perform I/O. Callers treat a verdict as an
        observation about an answer that has already been produced — it never
        changes, delays, or blocks what the member receives.
        """
        ...
