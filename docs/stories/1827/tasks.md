# Tasks: Consistent Summarization Behavior Between ingest-website and ingest-space

**Story:** alkem-io/alkemio#1827
**Date:** 2026-04-08

## Task List

### T1: Add `summarize_enabled` config field and `summarize_concurrency` validation

**File:** `core/config.py`
**Depends on:** none
**Acceptance criteria:**
- `BaseConfig.summarize_enabled` field exists with default `True`, type `bool`.
- `BaseConfig` validator rejects `summarize_concurrency < 0` with `ValueError`.
**Tests:** `tests/core/test_config_validation.py` — test default value, test negative concurrency rejection.

### T2: Align `ingest-website` pipeline assembly

**File:** `plugins/ingest_website/plugin.py`
**Depends on:** T1
**Acceptance criteria:**
- `DocumentSummaryStep` and `BodyOfKnowledgeSummaryStep` are always included when `summarize_enabled=True`.
- When `summarize_enabled=False`, both summary steps are skipped.
- `concurrency` passed to `DocumentSummaryStep` is `max(config.summarize_concurrency, 1)`.
- Uses `IngestWebsiteConfig` instead of `BaseConfig`.
**Tests:** `tests/plugins/test_ingest_website.py` — updated pipeline composition test, new summarize_enabled tests.

### T3: Align `ingest-space` pipeline assembly

**File:** `plugins/ingest_space/plugin.py`
**Depends on:** T1
**Acceptance criteria:**
- Reads `summarize_concurrency` and `summarize_enabled` from `IngestSpaceConfig`.
- When `summarize_enabled=False`, both summary steps are skipped.
- `concurrency` passed to `DocumentSummaryStep` is `max(config.summarize_concurrency, 1)`.
**Tests:** `tests/plugins/test_ingest_space.py` — new config-driven pipeline tests.

### T4: Update existing `test_ingest_website` test

**File:** `tests/plugins/test_ingest_website.py`
**Depends on:** T2
**Acceptance criteria:**
- `test_pipeline_composition` updated to reflect new behavior (summary steps included by default).
- Test still passes and verifies pipeline runs correctly.

### T5: Add new tests for summarization consistency

**Files:** `tests/plugins/test_ingest_website.py`, `tests/plugins/test_ingest_space.py`, `tests/core/test_config_validation.py`
**Depends on:** T1, T2, T3
**Acceptance criteria:**
- Test: both plugins include summary steps with default config.
- Test: `SUMMARIZE_ENABLED=false` skips summary steps in both plugins.
- Test: `summarize_concurrency=0` maps to `concurrency=1` in both plugins.
- Test: negative `summarize_concurrency` raises `ValueError`.
- Test: `summarize_enabled` defaults to `True`.

### T6: Verify all exit gates pass

**Depends on:** T1-T5
**Acceptance criteria:**
- `poetry run pytest` passes.
- `poetry run ruff check core/ plugins/ tests/` passes.
- `poetry run pyright core/ plugins/` passes.
