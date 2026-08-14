"""Port for re-ordering retrieval candidates before context assembly.

Retrieval ranks by vector distance alone, which compresses a passage's whole
meaning into one comparison. This port is the seam where a second opinion is
applied to that ordering.

**It returns a permutation, not a container.** The two call sites hold
different shapes — expert has four parallel lists, guidance has a list of
``(document, Source)`` pairs — and a list of indices serves both. It also
makes index alignment structural: a caller applies the same permutation to
every list it holds, so nothing can drift out of step and attribute one
passage's text to another passage's source.

Primitives only. No repo type appears in the signature, which is what lets the
zero-egress check assert, statically, that nothing on this path can perform
I/O.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class RerankerPort(Protocol):
    """Re-orders retrieval candidates."""

    def rerank(
        self,
        query: str,
        documents: list[str],
        vector_scores: list[float],
        top_k: int | None = None,
    ) -> list[int]:
        """Return candidate indices in re-ranked order, best first.

        ``vector_scores`` are similarity scores where higher is better — the
        existing ``1.0 - distance`` convention, *not* raw distances. Passing
        distances would silently invert the ranking, so callers convert first.

        ``top_k=None`` returns the full ordering; any other value returns
        exactly that many leading elements of the same ordering.

        Synchronous on purpose: scoring is pure CPU with no I/O, and an
        ``async`` signature would imply a network call that must never exist
        here.
        """
        ...
