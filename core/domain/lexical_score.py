"""Score how strongly a passage matches the words a member actually typed.

Vector retrieval answers "is this passage about the same thing?". This answers
a narrower question — "does this passage contain the terms that make the
question specific?" — and the two disagree in a way that matters: a page
that is *about* spaces in general can out-rank the one page that documents
the procedure being asked about.

Deliberately not a neural model. Everything here is stdlib arithmetic, which
is what allows the whole re-ranking path to be provably free of I/O and to
add nothing to the runtime image.

Pure: no I/O, no configuration, no clock. What comes out is a function of what
goes in.
"""

from __future__ import annotations

import math
import re
from collections import Counter

#: Runs of letters and digits, over lowercased text. Digits are kept so
#: version numbers and identifiers survive as terms.
_TOKEN_RE = re.compile(r"[a-z0-9]+")

#: BM25 term-frequency saturation. Past roughly this many occurrences, another
#: repetition adds almost nothing — which is what stops a passage that merely
#: repeats a word from beating one that actually answers the question.
K1 = 1.2

#: BM25 length normalisation. At 0.75, a long passage is discounted for its
#: length but not erased by it; a genuinely thorough answer should still be
#: able to win.
B = 0.75

#: Characters of query text considered. Scoring is synchronous and runs on the
#: event loop, so an oversized message would block every other message in the
#: process while it was tokenised — measured at hundreds of milliseconds for a
#: multi-megabyte query, against a pod limited to ~1.5 CPU. No question a
#: person writes approaches this; anything beyond it is not a query.
MAX_QUERY_CHARS = 8_000

#: Distinct query terms scored. Past this the marginal term adds nothing to
#: ranking, and the cost is per-term per-document.
MAX_QUERY_TERMS = 64

#: Characters of each document considered. Retrieval returns chunks, and the
#: deployed chunk size is an order of magnitude below this — so in normal
#: operation nothing is truncated. It bounds the pathological case where a
#: caller passes whole documents rather than chunks.
MAX_DOCUMENT_CHARS = 100_000


def tokenize(text: str) -> list[str]:
    """Split text into lowercased alphanumeric terms.

    Tolerates ``None`` and other non-strings: a malformed entry in a store
    result should cost that one passage its lexical signal, not raise and turn
    a working answer into an error.
    """
    if not isinstance(text, str):
        return []
    return _TOKEN_RE.findall(text.lower())


def compute_idf(docs_tokens: list[list[str]]) -> dict[str, float]:
    """Inverse document frequency across the candidate set.

    A term appearing in one of twenty candidates discriminates between them; a
    term in all twenty does not. This is what separates the distinctive part
    of a question from its filler without needing a stop-word list.

    Computed over the ~20 retrieved candidates, not the corpus — true corpus
    statistics would need an index the service does not keep, or extra queries
    on the request path. It is a local approximation, and it is the right one
    for the job: the question here is only ever *which of these candidates*
    to prefer.
    """
    n = len(docs_tokens)
    if not n:
        return {}

    df: Counter[str] = Counter()
    for tokens in docs_tokens:
        for term in set(tokens):
            df[term] += 1

    # Always positive: at df == n the numerator is still 0.5, so a term common
    # to every candidate scores near zero rather than negative. A negative IDF
    # would let a ubiquitous term actively push a passage down.
    return {
        term: math.log(1 + (n - count + 0.5) / (count + 0.5))
        for term, count in df.items()
    }


def lexical_scores(query: str, documents: list[str]) -> list[float]:
    """Score every document against the query's terms, in ``[0, 1]``.

    Clamped at 1.0 deliberately. The BM25 saturation factor
    ``count*(K1+1)/(count + K1*norm)`` approaches ``K1+1`` as ``norm`` tends to
    zero, which happens when a matching document is far shorter than the pool
    average — a bare heading among long prose. Unclamped that reaches ~2.19,
    and today nothing notices because the caller min-max rescales it away. It
    would stop being invisible the moment a second implementation behind
    ``RerankerPort``, or any telemetry, took the documented range at its word.

    Returns all zeros — never raises — when there is nothing to measure: no
    documents, an empty or whitespace query, a query whose terms appear
    nowhere, or text in a script this tokenizer does not segment. "No lexical
    signal" is a legitimate answer, and the caller's blend then falls back to
    vector order rather than to noise.
    """
    if not documents:
        return []

    # Bounded before tokenising, not after: the cost being capped is the
    # tokenisation itself, and this runs synchronously on the event loop.
    query_terms = set(tokenize(query[:MAX_QUERY_CHARS]))
    if not query_terms:
        return [0.0] * len(documents)
    if len(query_terms) > MAX_QUERY_TERMS:
        # Deterministic, so the same question always scores the same way.
        query_terms = set(sorted(query_terms)[:MAX_QUERY_TERMS])

    docs_tokens = [
        tokenize(doc[:MAX_DOCUMENT_CHARS] if isinstance(doc, str) else doc)
        for doc in documents
    ]
    lengths = [len(t) for t in docs_tokens]
    avg_len = (sum(lengths) / len(lengths)) if lengths else 0.0

    idf = compute_idf(docs_tokens)

    # Divide by the query's total IDF mass so the result is a *fraction of the
    # question matched*, comparable across queries, rather than an unbounded
    # sum that grows with query length.
    total_idf = sum(idf.get(term, 0.0) for term in query_terms)
    if total_idf <= 0.0:
        return [0.0] * len(documents)

    scores: list[float] = []
    for tokens, length in zip(docs_tokens, lengths):
        freq = Counter(tokens)
        score = 0.0
        for term in query_terms:
            count = freq.get(term, 0)
            if not count:
                continue
            norm = 1.0 - B + B * (length / avg_len if avg_len else 1.0)
            score += idf.get(term, 0.0) * (count * (K1 + 1.0)) / (count + K1 * norm)
        scores.append(min(1.0, score / total_idf))
    return scores
