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


def tokenize(text: str) -> list[str]:
    """Split text into lowercased alphanumeric terms."""
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

    Returns all zeros — never raises — when there is nothing to measure: no
    documents, an empty or whitespace query, a query whose terms appear
    nowhere, or text in a script this tokenizer does not segment. "No lexical
    signal" is a legitimate answer, and the caller's blend then falls back to
    vector order rather than to noise.
    """
    if not documents:
        return []

    query_terms = set(tokenize(query))
    if not query_terms:
        return [0.0] * len(documents)

    docs_tokens = [tokenize(doc) for doc in documents]
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
        scores.append(score / total_idf)
    return scores
