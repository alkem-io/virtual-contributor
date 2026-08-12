"""Canonical Chroma metadata filters for retrieval.

Stored collections contain three ingestion generations.  Oldest content entries
lack ``embeddingType``, while old knowledge-base overview entries are marked
only by ``type``.  The factual predicate therefore excludes summaries with
``$ne`` rather than selecting ``embeddingType == 'chunk'``: Chroma's modern
missing-key semantics retain legacy content while the second exclusion removes
unmarked overview records.
"""

FACTUAL_WHERE = {
    "$and": [
        {"embeddingType": {"$ne": "summary"}},
        {"type": {"$ne": "bodyOfKnowledgeSummary"}},
    ]
}

SUMMARIES_WHERE = {
    "$or": [
        {"embeddingType": {"$eq": "summary"}},
        {"type": {"$eq": "bodyOfKnowledgeSummary"}},
    ]
}
