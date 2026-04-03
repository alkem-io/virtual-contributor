"""Rich summarization prompt templates — aligned with original repo prompts."""

DOCUMENT_REFINE_SYSTEM = (
    "Expert at creating structured, information-dense summaries for semantic search and vector retrieval.\n\n"
    "FORMAT:\n"
    "- Use markdown headers (### or **bold**) to organize content by theme\n"
    "- Use bullet points for lists of related facts\n"
    "- Each bullet must contain specific facts with dates, names, or numbers\n\n"
    "REQUIREMENTS:\n"
    "- Preserve ALL key entities: names, titles, dates, numbers, technical terms, URLs, references\n"
    "- Use concrete, factual language - no vague descriptions\n"
    "- Include domain-specific terminology and searchable keywords\n"
    "- Maximize information density - every sentence must convey specific facts\n\n"
    "FORBIDDEN:\n"
    "- No repetitive sentence patterns\n"
    "- No generic filler statements without specific details\n"
    "- No vague phrases like \"various things\" or \"several aspects\"\n"
    "- No interpretations or opinions not in source\n"
    "- Never repeat the same information twice"
)

DOCUMENT_REFINE_INITIAL = (
    "Create a structured summary of the following content using markdown headers and bullet points.\n"
    "Include only essential facts and entities - no filler or repetition.\n"
    "Target length: around {budget} characters. You may exceed this if needed to preserve important information.\n\n"
    "Content:\n{text}\n\nSummary:"
)

DOCUMENT_REFINE_SUBSEQUENT = (
    "Refine this summary by integrating new information.\n"
    "Maintain markdown structure with headers and bullet points.\n"
    "Target length: around {budget} characters. You may exceed this if needed to preserve important information.\n\n"
    "Current summary:\n{summary}\n\n"
    "New content to integrate:\n{text}\n\n"
    "Instructions:\n"
    "1. Merge new facts into existing sections or create new sections as needed\n"
    "2. Remove any redundancy - never repeat the same fact twice\n"
    "3. Preserve ALL specific entities, dates, and details from both sources\n"
    "4. Keep bullet points factual and specific - no generic statements\n\n"
    "Refined summary:"
)

BOK_OVERVIEW_SYSTEM = (
    "Create a structured high-level overview of an entire body of knowledge for semantic search retrieval.\n\n"
    "This summary helps determine if this body of knowledge is relevant to user queries.\n\n"
    "FORMAT:\n"
    "- Use markdown headers (### or **bold**) to organize by theme\n"
    "- Use bullet points for lists of entities, dates, and connections\n"
    "- Each section should contain specific, searchable facts\n\n"
    "REQUIREMENTS:\n"
    "- Capture overall scope, themes, and domains covered\n"
    "- Preserve key cross-cutting entities: participant names, organizations, major initiatives\n"
    "- Include temporal scope (date ranges, time periods)\n"
    "- Identify main topic areas and their relationships\n"
    "- Use searchable terminology\n\n"
    "FORBIDDEN:\n"
    "- No repetitive sentence patterns\n"
    "- No generic filler statements\n"
    "- No redundant information - each fact appears only once"
)

BOK_OVERVIEW_INITIAL = (
    "Create a structured overview of this body of knowledge using markdown headers and bullet points.\n"
    "Include only essential themes, entities, and connections - no filler or repetition.\n"
    "Target length: around {budget} characters. You may exceed this if needed to preserve important information.\n\n"
    "This is a collection of summaries from individual documents:\n{text}\n\nOverview summary:"
)

BOK_OVERVIEW_SUBSEQUENT = (
    "Refine this body of knowledge overview by integrating additional information.\n"
    "Maintain markdown structure with headers and bullet points.\n"
    "Target length: around {budget} characters. You may exceed this if needed to preserve important information.\n\n"
    "Current overview:\n{summary}\n\n"
    "Additional document summaries:\n{text}\n\n"
    "Instructions:\n"
    "1. Merge new themes into existing sections or create new sections as needed\n"
    "2. Remove any redundancy - never repeat the same fact or entity twice\n"
    "3. Add newly discovered entities, dates, or connections\n"
    "4. Keep all content specific and factual - no generic statements\n\n"
    "Refined overview:"
)
