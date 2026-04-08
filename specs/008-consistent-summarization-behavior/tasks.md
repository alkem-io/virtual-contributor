# Tasks: Consistent Summarization Behavior Between Ingest Plugins

**Story:** alkem-io/alkemio#1827
**Date:** 2026-04-08

## Task 1: Add `summarize_enabled` to `BaseConfig`

**File:** `core/config.py`
**Dependencies:** None
**Acceptance criteria:**
- `BaseConfig` has a `summarize_enabled: bool = True` field
- Default value is `True`
- Env var `SUMMARIZE_ENABLED` controls it
**Tests:** Config instantiation with and without env var

## Task 2: Update `ingest-website` plugin

**File:** `plugins/ingest_website/plugin.py`
**Dependencies:** Task 1
**Acceptance criteria:**
- Accept `summarize_enabled: bool = True` and `summarize_concurrency: int = 8` as constructor parameters
- Remove inline `BaseConfig()` instantiation from `handle()`
- Conditionally include/exclude summary steps based on `self._summarize_enabled`
- Pass `concurrency=max(1, self._summarize_concurrency)` to `DocumentSummaryStep`
- Pipeline includes summary steps when `summarize_enabled=True`
- Pipeline excludes summary steps when `summarize_enabled=False`
**Tests:** `test_pipeline_with_summarize_enabled`, `test_pipeline_with_summarize_disabled`

## Task 3: Update `ingest-space` plugin

**File:** `plugins/ingest_space/plugin.py`
**Dependencies:** Task 1
**Acceptance criteria:**
- Accept `summarize_enabled: bool = True` and `summarize_concurrency: int = 8` as constructor parameters
- Conditionally include/exclude summary steps based on `self._summarize_enabled`
- Pass `concurrency=max(1, self._summarize_concurrency)` to `DocumentSummaryStep`
- Pipeline includes summary steps when `summarize_enabled=True`
- Pipeline excludes summary steps when `summarize_enabled=False`
**Tests:** `test_pipeline_with_summarize_enabled`, `test_pipeline_with_summarize_disabled`

## Task 4: Update `main.py` to inject new parameters

**File:** `main.py`
**Dependencies:** Tasks 1, 2, 3
**Acceptance criteria:**
- Inject `summarize_enabled` and `summarize_concurrency` from config into ingest plugins via constructor
- Pattern follows existing `chunk_threshold` injection
**Tests:** Covered by integration tests

## Task 5: Update `.env.example`

**File:** `.env.example`
**Dependencies:** Task 1
**Acceptance criteria:**
- New `SUMMARIZE_ENABLED=true` entry with comment explaining its purpose
- Placed near existing summarization config entries
**Tests:** N/A (documentation)

## Task 6: Add/update tests for `ingest-website`

**File:** `tests/plugins/test_ingest_website.py`
**Dependencies:** Tasks 1, 2
**Acceptance criteria:**
- Test that pipeline includes `DocumentSummaryStep` and `BodyOfKnowledgeSummaryStep` when `summarize_enabled=True`
- Test that pipeline excludes both summary steps when `summarize_enabled=False`
- Existing `test_pipeline_composition` updated to match new behavior
**Tests:** Self (test file)

## Task 7: Add/update tests for `ingest-space`

**File:** `tests/plugins/test_ingest_space.py`
**Dependencies:** Tasks 1, 3
**Acceptance criteria:**
- Test that pipeline includes summary steps when `summarize_enabled=True`
- Test that pipeline excludes summary steps when `summarize_enabled=False`
- Test that `summarize_concurrency` is passed through to `DocumentSummaryStep`
**Tests:** Self (test file)

## Task 8: Verify all tests pass

**Dependencies:** Tasks 1-7
**Acceptance criteria:**
- `poetry run pytest` passes with zero failures
- `poetry run ruff check core/ plugins/ tests/` passes
- `poetry run pyright core/ plugins/` passes
