# Clarifications

**Iteration count:** 1

## Clarification 1: Mutation strategy for context.chunks during gather

**Question:** Should summary chunks be appended to `context.chunks` inside each concurrent coroutine (requiring a lock) or collected into a local list and bulk-appended after `asyncio.gather()` completes?

**Chosen answer:** Collect results into a local list and bulk-append after gather. This avoids any need for `asyncio.Lock` on the list since `asyncio.gather()` runs coroutines on the same event loop (no true parallelism), but the gather-then-append pattern is cleaner, easier to reason about, and prevents interleaving with any future step that might read `context.chunks` during execution. The same pattern applies to `context.document_summaries` and `context.errors`.

**Rationale:** The collect-then-merge pattern is the standard asyncio best practice for concurrent result aggregation. It makes the code testable (results are deterministic regardless of completion order) and avoids subtle bugs if asyncio internals change or if the code is later adapted for multi-threaded executors.

## Clarification 2: Error handling -- should gather use return_exceptions?

**Question:** Should `asyncio.gather(*tasks, return_exceptions=True)` be used, or should each coroutine handle its own exceptions internally?

**Chosen answer:** Each coroutine catches its own exceptions internally and returns a result object (success with data, or failure with error message). This preserves the existing per-document error isolation pattern (the current sequential loop has a try/except per document). `return_exceptions=True` would require post-gather type-checking of results, which is less readable.

**Rationale:** Matches the existing error handling pattern in the sequential implementation. Each document's summarization failure is logged and appended to errors without affecting others.

## Clarification 3: Ordering of summary chunks in context.chunks

**Question:** Does the order of summary chunks in `context.chunks` matter? The concurrent execution may complete in a different order than the sequential iteration.

**Chosen answer:** Order does not matter. Downstream steps (EmbedStep, StoreStep) process all chunks regardless of order. The BoK summary step iterates `seen_doc_ids` in chunk order, but document summaries are looked up by `doc_id` key in the `document_summaries` dict, so chunk order is irrelevant. We will sort the results by doc_id before appending to maintain deterministic output for testing purposes.

**Rationale:** Deterministic ordering aids debugging and test assertions. Sorting by doc_id is cheap (typically <50 documents) and removes any flakiness from tests that check chunk list contents.

## Clarification 4: Concurrency=0 behavior

**Question:** What should happen when `concurrency=0`? The existing code does not validate this.

**Chosen answer:** `asyncio.Semaphore(0)` would deadlock (acquire would block forever). Add a validation in `__init__` that `concurrency >= 1`, raising `ValueError` if not. This is consistent with the existing `chunk_threshold >= 1` validation already present.

**Rationale:** Defensive programming. The config field `summarize_concurrency` defaults to 8, but a user could set it to 0. Failing fast with a clear error is better than a silent deadlock.

## Clarification 5: Logging during concurrent execution

**Question:** Should the "Summarizing document..." and "Summarized document..." log messages still be emitted per-document during concurrent execution?

**Chosen answer:** Yes. The logging calls are inside each coroutine and are safe in asyncio (logging is thread-safe in CPython, and asyncio coroutines don't truly run in parallel). The log messages help operators monitor progress of a concurrent batch.

**Rationale:** Preserves existing observability. No code change needed for logging.
