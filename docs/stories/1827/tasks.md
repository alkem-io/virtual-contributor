# Tasks: Story #1827

## Task 1: Add `summarize_enabled` config field and concurrency validation
**File:** `core/config.py`
**Depends on:** None
**Acceptance criteria:**
- `BaseConfig` has field `summarize_enabled: bool = True`.
- Validation rejects `summarize_concurrency < 0` with a clear error message.
**Tests:** `tests/core/test_config_validation.py` -- test `summarize_concurrency=-1` raises ValidationError; test `summarize_enabled` defaults to True.

## Task 2: Update IngestWebsitePlugin to use constructor-injected config
**File:** `plugins/ingest_website/plugin.py`
**Depends on:** Task 1
**Acceptance criteria:**
- Constructor accepts `summarize_enabled: bool = True` and `summarize_concurrency: int = 8`.
- Inline `BaseConfig()` instantiation removed from `handle()`.
- Summary steps included when `summarize_enabled=True`, skipped when `False`.
- Effective concurrency is `max(1, summarize_concurrency)`.
**Tests:** `tests/plugins/test_ingest_website.py` -- three scenarios (enabled+concurrent, enabled+zero-concurrency, disabled).

## Task 3: Update IngestSpacePlugin to honor summarize_enabled
**File:** `plugins/ingest_space/plugin.py`
**Depends on:** Task 1
**Acceptance criteria:**
- Constructor accepts `summarize_enabled: bool = True` and `summarize_concurrency: int = 8`.
- Summary steps included when `summarize_enabled=True`, skipped when `False`.
- Concurrency parameter passed to `DocumentSummaryStep`.
**Tests:** `tests/plugins/test_ingest_space.py` -- three scenarios (enabled+concurrent, enabled+zero-concurrency, disabled).

## Task 4: Wire new parameters in main.py
**File:** `main.py`
**Depends on:** Task 2, Task 3
**Acceptance criteria:**
- `summarize_enabled` and `summarize_concurrency` injected into plugins that accept them, following existing `chunk_threshold` pattern.
- Effective concurrency computation (`max(1, ...)`) is done at injection time.
**Tests:** Covered implicitly by plugin tests; no separate main.py test needed.

## Task 5: Update and add tests
**Files:** `tests/plugins/test_ingest_website.py`, `tests/plugins/test_ingest_space.py`, `tests/core/test_config.py`
**Depends on:** Task 2, Task 3
**Acceptance criteria:**
- Existing `test_pipeline_composition` updated to not rely on `summarize_concurrency=0` as disable.
- Three new test scenarios per plugin: enabled+concurrent, enabled+sequential, disabled.
- Config validation test for negative concurrency.
- All tests pass.
**Tests:** Self-evident -- the tests themselves.
