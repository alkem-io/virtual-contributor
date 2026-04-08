# Clarifications: Implement Actual Concurrency in DocumentSummaryStep

**Story:** alkem-io/alkemio#1823
**Clarify iteration:** 1

---

## Resolved Ambiguities

### C-1: Thread-safety strategy for context mutation

**Question:** Should we use `asyncio.Lock` to protect concurrent writes to `context.chunks` and `context.document_summaries`, or collect results locally and apply them after `asyncio.gather` completes?

**Chosen answer:** Collect results locally in a list of tuples `(doc_id, summary, summary_chunk)` and apply them to `context` after `gather` completes.

**Rationale:** asyncio runs on a single thread with cooperative multitasking, so true race conditions only occur if two coroutines yield (await) between a read and a write on the same mutable structure. However, the safer and more idiomatic pattern is to collect results from each task and batch-apply them post-gather. This avoids any subtle ordering issues and makes the code easier to reason about. It also preserves deterministic ordering of summary chunks (sorted by doc_id or original order).

### C-2: Ordering of summary chunks in context.chunks

**Question:** The current sequential loop appends summary chunks in document iteration order. With concurrent execution, should we preserve this order?

**Chosen answer:** Yes, preserve the original iteration order of `docs_to_summarize`.

**Rationale:** While the pipeline does not strictly require ordering of chunks in `context.chunks`, deterministic ordering simplifies testing, debugging, and reproducibility. After gather, we sort results by the original index before appending to `context.chunks`.

### C-3: Error handling within asyncio.gather

**Question:** Should `asyncio.gather` use `return_exceptions=True` or should each coroutine have its own try/except?

**Chosen answer:** Each coroutine wraps its work in try/except, returning a sentinel error result. We do NOT use `return_exceptions=True`.

**Rationale:** Per-coroutine try/except gives finer control over error messages and allows us to return structured results (success with summary data, or failure with error string) rather than mixing Exception objects with result tuples. This matches the existing per-document error handling pattern in the sequential loop.

### C-4: Should concurrency=0 be treated as "unlimited"?

**Question:** The constructor validates `chunk_threshold >= 1` but does not validate `concurrency`. Should `concurrency=0` or negative values be handled?

**Chosen answer:** Add a validation that `concurrency >= 1` in `__init__`, raising `ValueError` for invalid values.

**Rationale:** A semaphore with 0 or negative value would deadlock or raise. Explicit validation matches the existing `chunk_threshold` validation pattern.

### C-5: Does the concurrency parameter from config actually get wired to the step?

**Question:** The story says "`summarize_concurrency` just needs to be wired through." Is it already wired?

**Chosen answer:** After inspecting the codebase, the `summarize_concurrency` config field exists at `core/config.py:270` with default 8. The wiring from config to step constructor must be verified in the ingest plugin code. If not wired, we wire it.

**Rationale:** The story explicitly mentions this needs to be checked and wired if missing.

**Finding:** After inspecting the codebase:
- `ingest_website/plugin.py:105` — already wired: `concurrency=config.summarize_concurrency`
- `ingest_space/plugin.py:89` — NOT wired: `DocumentSummaryStep(llm_port=summary_llm, chunk_threshold=self._chunk_threshold)` uses default concurrency=8 but does not read from config. This should be wired as part of this story.

### C-6: Should ingest_space also wire summarize_concurrency from config?

**Question:** The ingest_space plugin constructs `DocumentSummaryStep` without passing the `concurrency` parameter from config. Should this be fixed?

**Chosen answer:** Yes, wire `concurrency=config.summarize_concurrency` in `ingest_space/plugin.py` analogous to `ingest_website/plugin.py`.

**Rationale:** Both plugins use the same step and the same config field. Consistency requires both to respect the config value. The default of 8 happens to match, but explicit wiring ensures future config changes apply uniformly.

---

## Clarify Iteration 2

No further ambiguities found. All questions resolved. Clean pass.
