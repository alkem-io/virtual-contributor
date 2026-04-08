# Tasks: Consistent Summarization Behavior Between ingest-website and ingest-space

**Story:** alkem-io/alkemio#1827
**Date:** 2026-04-08

## Task List (dependency-ordered)

### Task 1: Add `summarize_enabled` field and `summarize_concurrency` validation to `BaseConfig`

**File:** `core/config.py`

**Changes:**
- Add `summarize_enabled: bool = True` field to `BaseConfig`.
- Add validation in `_resolve_backward_compat_and_validate`: reject `summarize_concurrency < 0`.

**Acceptance Criteria:**
- `BaseConfig(summarize_enabled=True)` and `BaseConfig(summarize_enabled=False)` work.
- `BaseConfig(summarize_concurrency=-1)` raises `ValueError`.
- `BaseConfig(summarize_concurrency=0)` is accepted (valid value).

**Tests:** `tests/core/test_config_validation.py` -- add negative concurrency test and summarize_enabled field test.

**Dependencies:** None.

---

### Task 2: Update `IngestWebsitePlugin` to use constructor-injected config

**File:** `plugins/ingest_website/plugin.py`

**Changes:**
- Add `summarize_enabled: bool = True` and `summarize_concurrency: int = 8` keyword-only constructor parameters.
- Remove inline `from core.config import BaseConfig; config = BaseConfig()` from `handle()`.
- Gate summary steps on `self._summarize_enabled` instead of `config.summarize_concurrency > 0`.
- Pass `max(1, self._summarize_concurrency)` as `concurrency` to `DocumentSummaryStep`.

**Acceptance Criteria:**
- When `summarize_enabled=True`, both summary steps are in the pipeline.
- When `summarize_enabled=False`, both summary steps are absent.
- When `summarize_concurrency=0`, summary steps are included (not skipped) and concurrency defaults to 1.

**Tests:** `tests/plugins/test_ingest_website.py` -- update existing test, add new tests.

**Dependencies:** Task 1.

---

### Task 3: Update `IngestSpacePlugin` to accept summarization config

**File:** `plugins/ingest_space/plugin.py`

**Changes:**
- Add `summarize_enabled: bool = True` and `summarize_concurrency: int = 8` keyword-only constructor parameters.
- Gate summary steps on `self._summarize_enabled`.
- Pass `max(1, self._summarize_concurrency)` as `concurrency` to `DocumentSummaryStep`.

**Acceptance Criteria:**
- When `summarize_enabled=True`, both summary steps are in the pipeline (same as current behavior).
- When `summarize_enabled=False`, both summary steps are absent.
- `summarize_concurrency` is forwarded to `DocumentSummaryStep`.

**Tests:** `tests/plugins/test_ingest_space.py` -- add new tests.

**Dependencies:** Task 1.

---

### Task 4: Update `main.py` to inject `summarize_enabled` and `summarize_concurrency`

**File:** `main.py`

**Changes:**
- In the plugin construction section, inject `summarize_enabled` and `summarize_concurrency` from config into plugins that accept those parameters (same pattern as `chunk_threshold` and `summarize_llm`).

**Acceptance Criteria:**
- Ingest plugins receive `summarize_enabled` and `summarize_concurrency` from config.
- Non-ingest plugins are unaffected.

**Tests:** Covered by integration through plugin tests. No separate unit test needed (main.py wiring is tested via existing startup tests).

**Dependencies:** Tasks 2, 3.

---

### Task 5: Update `.env.example`

**File:** `.env.example`

**Changes:**
- Add `SUMMARIZE_ENABLED=true` with explanatory comment.
- Add `SUMMARIZE_CONCURRENCY=8` to document the existing default explicitly.

**Acceptance Criteria:**
- New fields are documented with clear comments.

**Tests:** None (documentation only).

**Dependencies:** Task 1.

---

### Task 6: Update and add tests

**Files:**
- `tests/plugins/test_ingest_website.py`
- `tests/plugins/test_ingest_space.py`
- `tests/core/test_config_validation.py`

**Changes:**
- Fix existing `test_pipeline_composition` in `test_ingest_website.py` (remove mock of `summarize_concurrency=0` as disabling summarization).
- Add `test_summarize_enabled_true_includes_summary_steps` for both plugins.
- Add `test_summarize_enabled_false_excludes_summary_steps` for both plugins.
- Add `test_summarize_concurrency_zero_does_not_skip_summary` for ingest-website.
- Add config validation tests for negative `summarize_concurrency` and `summarize_enabled`.

**Acceptance Criteria:**
- All new tests pass.
- All existing tests pass.

**Dependencies:** Tasks 2, 3.
