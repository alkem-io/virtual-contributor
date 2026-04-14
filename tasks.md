# Tasks: Skip upsert for unchanged chunks in StoreStep

**Story:** #1825

## Task List

### T1: Add unchanged-chunk filter to StoreStep
**File:** `core/domain/pipeline/steps.py`
**Depends on:** none
**Acceptance criteria:**
- `StoreStep.execute()` filters out chunks whose `content_hash` is in `context.unchanged_chunk_hashes`
- Unchanged chunks are excluded before the upsert batching loop
- The "skipped N chunks without embeddings" error message only counts chunks genuinely lacking embeddings, not unchanged ones
- An INFO log message reports how many unchanged chunks were skipped
- `context.chunks_stored` only counts actually-written chunks
**Tests:** T2, T3, T4, T5

### T2: Test that unchanged chunks are skipped
**File:** `tests/core/domain/test_pipeline_steps.py`
**Depends on:** T1
**Acceptance criteria:**
- Test creates a PipelineContext with `unchanged_chunk_hashes` containing a hash
- A chunk with matching `content_hash` and a valid embedding is present
- After StoreStep.execute(), that chunk is NOT in the store
- `context.chunks_stored` does not count the unchanged chunk
**Test:** `test_skips_unchanged_chunks`

### T3: Test that changed chunks are stored alongside unchanged
**File:** `tests/core/domain/test_pipeline_steps.py`
**Depends on:** T1
**Acceptance criteria:**
- Context has both changed and unchanged chunks
- Only changed chunks are stored
- chunks_stored count equals number of changed chunks only
**Test:** `test_stores_changed_chunks_alongside_unchanged`

### T4: Test that summary/BoK chunks are not filtered
**File:** `tests/core/domain/test_pipeline_steps.py`
**Depends on:** T1
**Acceptance criteria:**
- A summary chunk (content_hash=None) is present alongside unchanged content chunks
- The summary chunk is stored despite unchanged_chunk_hashes being populated
**Test:** `test_unchanged_filter_does_not_affect_summary_chunks`

### T5: Test backward compatibility when unchanged_hashes is empty
**File:** `tests/core/domain/test_pipeline_steps.py`
**Depends on:** T1
**Acceptance criteria:**
- When `unchanged_chunk_hashes` is empty, all embedded chunks are stored (no regression)
- Identical behavior to pre-change code
**Test:** `test_no_filter_when_unchanged_hashes_empty`

## Dependency Order

```
T1 (implementation) --> T2, T3, T4, T5 (tests, parallel)
```
