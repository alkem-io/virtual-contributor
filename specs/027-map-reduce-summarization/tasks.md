# Tasks: Map-Reduce Summarization

**Branch**: `027-map-reduce-summarization` | **Date**: 2026-04-22 | **Spec**: [spec.md](spec.md)

---

## Phase 1: Foundational -- Map-Reduce Prompt Templates

### Task 1.1: Add document map prompt template
- [X] Add `DOCUMENT_MAP_TEMPLATE` to `core/domain/pipeline/prompts.py`
- [X] Template includes `{text}` and `{budget}` placeholders
- [X] Instructions: summarize one portion, capture entities verbatim, markdown format, no filler
- **File**: `core/domain/pipeline/prompts.py`

### Task 1.2: Add document reduce prompts
- [X] Add `DOCUMENT_REDUCE_SYSTEM` system prompt to `core/domain/pipeline/prompts.py`
- [X] Add `DOCUMENT_REDUCE_TEMPLATE` user prompt with `{summaries}` and `{budget}` placeholders
- [X] System prompt instructs merging partial summaries of the same document, deduplication, no new facts
- [X] User prompt uses `---` separator convention for partial summaries
- **File**: `core/domain/pipeline/prompts.py`

### Task 1.3: Add BoK map prompt template
- [X] Add `BOK_MAP_TEMPLATE` to `core/domain/pipeline/prompts.py`
- [X] Template includes `{text}` and `{budget}` placeholders
- [X] Instructions: extract themes, entities, facts for searchability from one section
- **File**: `core/domain/pipeline/prompts.py`

### Task 1.4: Add BoK reduce prompts
- [X] Add `BOK_REDUCE_SYSTEM` system prompt to `core/domain/pipeline/prompts.py`
- [X] Add `BOK_REDUCE_TEMPLATE` user prompt with `{summaries}` and `{budget}` placeholders
- [X] System prompt instructs merging partial overviews, deduplication, topic regrouping
- **File**: `core/domain/pipeline/prompts.py`

---

## Phase 2: US1 -- Core Map-Reduce Function and Step Rewiring

### Task 2.1: Implement `_map_reduce_summarize` async function
- [X] Add `_map_reduce_summarize()` module-level async function to `core/domain/pipeline/steps.py`
- [X] Accept `chunks`, `map_invoke`, `reduce_invoke`, `max_length`, prompt parameters, `concurrency`, `reduce_fanin`
- [X] Handle empty list (return `""`) and single chunk (single map call)
- [X] Calculate per-chunk budget as `max(500, max_length // max(2, len(chunks)))`
- [X] Create `asyncio.Semaphore(max(1, concurrency))` for bounded parallelism
- [X] Map phase: `asyncio.gather` over all chunks with semaphore-bounded `_map_one` coroutines
- [X] Filter out `None` results, sort by original index, collect successful minis
- [X] Log "Map-reduce: N/M partial summaries produced"
- [X] Reduce phase: loop while `len(minis) > 1`, batch by `reduce_fanin`
- [X] Single-element batches pass through without LLM call
- [X] Join batch summaries with `\n\n---\n\n` for reduce prompt
- [X] Log "Map-reduce: level X reduced N -> M" per level
- **File**: `core/domain/pipeline/steps.py`

### Task 2.2: Rewire `DocumentSummaryStep` to use map-reduce
- [X] Replace `_refine_summarize` call with `_map_reduce_summarize` in `_summarize_one`
- [X] Pass `map_invoke=self._llm.invoke`, `reduce_invoke=self._reduce_llm.invoke`
- [X] Use `DOCUMENT_REFINE_SYSTEM` as `map_system` (reuse existing system prompt)
- [X] Use `DOCUMENT_MAP_TEMPLATE` as `map_template`
- [X] Use `DOCUMENT_REDUCE_SYSTEM` as `reduce_system`, `DOCUMENT_REDUCE_TEMPLATE` as `reduce_template`
- [X] Set `concurrency=self._concurrency`, `reduce_fanin=10`
- **File**: `core/domain/pipeline/steps.py`

### Task 2.3: Rewire `BodyOfKnowledgeSummaryStep` to use map-reduce
- [X] Replace `_refine_summarize` call with `_map_reduce_summarize` in `execute`
- [X] Pass `map_invoke=self._map_llm.invoke`, `reduce_invoke=self._llm.invoke`
- [X] Use `BOK_OVERVIEW_SYSTEM` as `map_system`, `BOK_MAP_TEMPLATE` as `map_template`
- [X] Use `BOK_REDUCE_SYSTEM` as `reduce_system`, `BOK_REDUCE_TEMPLATE` as `reduce_template`
- [X] Set `concurrency=5`, `reduce_fanin=10`
- **File**: `core/domain/pipeline/steps.py`

### Task 2.4: Update imports in steps.py
- [X] Add imports for `DOCUMENT_MAP_TEMPLATE`, `DOCUMENT_REDUCE_SYSTEM`, `DOCUMENT_REDUCE_TEMPLATE`
- [X] Add imports for `BOK_MAP_TEMPLATE`, `BOK_REDUCE_SYSTEM`, `BOK_REDUCE_TEMPLATE`
- **File**: `core/domain/pipeline/steps.py`

---

## Phase 3: US2 -- Split-Model Support

### Task 3.1: Add `reduce_llm_port` parameter to `DocumentSummaryStep`
- [X] Add `reduce_llm_port: LLMPort | None = None` to `__init__` signature
- [X] Store as `self._reduce_llm = reduce_llm_port or llm_port`
- [X] Add docstring comment explaining the BoK model is used for reduce phase
- **File**: `core/domain/pipeline/steps.py`

### Task 3.2: Add `map_llm_port` parameter to `BodyOfKnowledgeSummaryStep`
- [X] Add `map_llm_port: LLMPort | None = None` to `__init__` signature
- [X] Store as `self._map_llm = map_llm_port or llm_port`
- [X] Add docstring comment explaining the cheap model is used for map phase
- **File**: `core/domain/pipeline/steps.py`

### Task 3.3: Wire `reduce_llm_port` in `IngestSpacePlugin`
- [X] Pass `reduce_llm_port=self._bok_llm or summary_llm` to `DocumentSummaryStep`
- **File**: `plugins/ingest_space/plugin.py`

### Task 3.4: Wire `map_llm_port` in `IngestSpacePlugin`
- [X] Pass `map_llm_port=summary_llm` to `BodyOfKnowledgeSummaryStep`
- **File**: `plugins/ingest_space/plugin.py`

### Task 3.5: Wire `reduce_llm_port` in `IngestWebsitePlugin`
- [X] Pass `reduce_llm_port=self._bok_llm or summary_llm` to `DocumentSummaryStep`
- **File**: `plugins/ingest_website/plugin.py`

### Task 3.6: Wire `map_llm_port` in `IngestWebsitePlugin`
- [X] Pass `map_llm_port=summary_llm` to `BodyOfKnowledgeSummaryStep`
- **File**: `plugins/ingest_website/plugin.py`

---

## Phase 4: US3 -- Error Tolerance

### Task 4.1: Map-phase error tolerance
- [X] Wrap each `_map_one` call in try/except
- [X] On failure: log WARNING with chunk index and error, return `(idx, None)`
- [X] Filter `None` results after gather -- proceed with partial list
- [X] If `minis` is empty after filtering, return `""`
- [X] Single-chunk failure returns `""` (not raises)
- **File**: `core/domain/pipeline/steps.py`

### Task 4.2: Reduce-phase error tolerance
- [X] Wrap each reduce batch call in try/except
- [X] On failure: log WARNING with level, batch index, input count, and error
- [X] Fallback: concatenate batch inputs with `\n\n---\n\n` separator
- [X] Append concatenated result to `next_level` so tree continues
- **File**: `core/domain/pipeline/steps.py`

---

## Phase 5: Polish -- Logging and Budget

### Task 5.1: Debug logging for map phase
- [X] Log chunk start: "Map chunk X/Y start (N chars)"
- [X] Log chunk completion: "Map chunk X/Y done (N chars in -> M chars out)"
- [X] Log at DEBUG level to avoid noise in production
- **File**: `core/domain/pipeline/steps.py`

### Task 5.2: Info logging for results
- [X] Log "Map-reduce: N/M partial summaries produced" at INFO level after map phase
- [X] Log "Map-reduce: level X reduced N -> M" at INFO level after each reduce level
- **File**: `core/domain/pipeline/steps.py`

### Task 5.3: Budget calculation
- [X] Per-chunk budget: `max(500, max_length // max(2, len(chunks)))`
- [X] Reduce budget: full `max_length` (passed as `budget` in reduce template)
- [X] Semaphore floor: `max(1, concurrency)` to prevent zero-semaphore deadlock
- **File**: `core/domain/pipeline/steps.py`
