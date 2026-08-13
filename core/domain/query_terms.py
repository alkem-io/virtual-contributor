"""Extract literal search terms from a member's question.

The lexical retrieval arm matches words as written, so it needs the words worth
matching on — names, identifiers, jargon — and not the connective tissue of a
sentence. A question is mostly the latter, and matching on "what" or "the"
would return everything, which is the same as returning nothing.

Pure: no I/O, no store, no configuration lookups. What comes out is a function
of what goes in.
"""

from __future__ import annotations

import re

#: Split on anything that is not a word character. Keeps digits, so version
#: numbers and identifiers survive.
_WORD_SPLIT_RE = re.compile(r"\W+", re.UNICODE)

#: Words too common to discriminate between passages. Deliberately a fixed,
#: inspectable list rather than a frequency model: it must be obvious why a
#: term was dropped, and it must not change under us as a corpus changes.
STOP_WORDS: frozenset[str] = frozenset({
    "a", "about", "above", "after", "again", "all", "also", "am", "an", "and",
    "any", "are", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can", "cannot", "could", "did",
    "do", "does", "doing", "done", "down", "during", "each", "few", "for",
    "from", "further", "had", "has", "have", "having", "he", "her", "here",
    "hers", "herself", "him", "himself", "his", "how", "i", "if", "in", "into",
    "is", "it", "its", "itself", "just", "me", "more", "most", "my", "myself",
    "no", "nor", "not", "now", "of", "off", "on", "once", "only", "or",
    "other", "ought", "our", "ours", "ourselves", "out", "over", "own", "same",
    "she", "should", "so", "some", "such", "than", "that", "the", "their",
    "theirs", "them", "themselves", "then", "there", "these", "they", "this",
    "those", "through", "to", "too", "under", "until", "up", "very", "was",
    "we", "were", "what", "when", "where", "which", "while", "who", "whom",
    "why", "will", "with", "would", "you", "your", "yours", "yourself",
    "yourselves",
})


def extract_terms(text: str, *, min_len: int, max_terms: int) -> list[str]:
    """Pull the terms worth matching literally out of a question.

    Casefolded, de-duplicated in first-seen order, and capped — a long question
    should not turn into a predicate with fifty alternatives, and the earliest
    distinctive words are usually the subject of the question.

    Returns an empty list when nothing survives, which the caller reads as
    "there is nothing here to match literally" and answers with the embedding
    arm alone.
    """
    if not text:
        return []

    seen: set[str] = set()
    terms: list[str] = []
    for raw in _WORD_SPLIT_RE.split(text):
        if not raw:
            continue
        term = raw.casefold()
        if len(term) < min_len:
            continue
        if term in STOP_WORDS:
            continue
        if term in seen:
            continue
        seen.add(term)
        terms.append(term)
        if len(terms) >= max_terms:
            break
    return terms
