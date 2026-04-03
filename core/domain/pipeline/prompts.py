"""Rich summarization prompt templates (FR-006 compliant)."""

DOCUMENT_REFINE_SYSTEM = (
    "You are a precise summarization assistant. "
    "Produce structured markdown summaries that preserve all key entities "
    "(names, dates, numbers, URLs, technical terms). "
    "Never repeat information already covered. "
    "Use bullet points and headings for clarity."
)

DOCUMENT_REFINE_INITIAL = (
    "Summarize the following text in at most {budget} characters. "
    "Output structured markdown preserving all key entities "
    "(names, dates, numbers, URLs, technical terms).\n\n{text}"
)

DOCUMENT_REFINE_SUBSEQUENT = (
    "Given this existing summary:\n{summary}\n\n"
    "And this additional text:\n{text}\n\n"
    "Produce a refined summary in at most {budget} characters. "
    "Merge new information without repeating what is already covered. "
    "Preserve all key entities (names, dates, numbers, URLs, technical terms). "
    "Output structured markdown."
)

BOK_OVERVIEW_SYSTEM = (
    "You are a knowledge-base analyst. "
    "Produce a single high-level overview that captures the main themes, "
    "key entities, and scope across all provided document summaries. "
    "Output structured markdown with headings and bullet points."
)

BOK_OVERVIEW_INITIAL = (
    "Create an overview of this knowledge base section in at most {budget} characters. "
    "Capture themes, key entities, and scope.\n\n{text}"
)

BOK_OVERVIEW_SUBSEQUENT = (
    "Given this existing overview:\n{summary}\n\n"
    "And this additional section:\n{text}\n\n"
    "Produce a refined overview in at most {budget} characters. "
    "Merge new themes without repeating what is already covered. "
    "Preserve all key entities. Output structured markdown."
)
