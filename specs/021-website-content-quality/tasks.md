# Tasks: Website Content Quality Improvements

**Input**: Design documents from `specs/021-website-content-quality/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md
**Organization**: Tasks grouped by cleanup layer.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: HTML-Level Boilerplate Filtering (US1)

**Purpose**: Remove boilerplate elements at the HTML parsing stage before semantic text extraction.

**Independent Test**: Parse HTML containing cookie banners, forms, dialogs, and aside elements. Verify extracted text excludes all boilerplate content.

### Implementation

- [X] T001 [US1] Expand `_STRIP_TAGS` list in plugins/ingest_website/html_parser.py to include `aside`, `form`, `dialog`, `noscript` alongside existing `script`, `style`, `nav`, `footer`, `header`
- [X] T002 [US1] Add `_BOILERPLATE_RE` compiled regex in plugins/ingest_website/html_parser.py matching class/ID patterns: cookie, consent, banner, popup, modal, gdpr, newsletter, subscribe, sign-up, opt-in, privacy-notice, bottom-bar, snackbar
- [X] T003 [US1] Add `_has_boilerplate_attr()` helper function in plugins/ingest_website/html_parser.py that checks a tag's class list and id against `_BOILERPLATE_RE`
- [X] T004 [US1] Update `extract_text()` in plugins/ingest_website/html_parser.py to call `soup.find_all(_has_boilerplate_attr)` and decompose matching elements before semantic tag extraction
- [X] T005 [US1] Add `Tag` to the BeautifulSoup import in plugins/ingest_website/html_parser.py and add `import re` for the regex module

**Checkpoint**: `extract_text()` strips both structural boilerplate tags and class/ID-matched boilerplate elements. All existing extraction behavior (semantic tags, fallback, min length) preserved.

---

## Phase 2: Cross-Page Paragraph Deduplication (US2)

**Purpose**: Remove paragraphs that appear across many pages, catching boilerplate that survived HTML-level filtering.

**Independent Test**: Pass 5+ extracted texts to `remove_cross_page_boilerplate()`. Verify paragraphs on >50% of pages are removed. Verify texts below `min_pages` threshold are returned unchanged.

### Implementation

- [X] T006 [US2] Add `remove_cross_page_boilerplate()` function in plugins/ingest_website/html_parser.py with parameters: `texts: list[str]`, `threshold: float = 0.5`, `min_pages: int = 4`
- [X] T007 [US2] Implement early return in `remove_cross_page_boilerplate()` when `len(texts) < min_pages`
- [X] T008 [US2] Implement `_normalize()` inner function for whitespace normalization and lowercasing of paragraphs
- [X] T009 [US2] Implement paragraph frequency counting: split on `\n\n`, normalize, skip paragraphs < 20 chars, count unique page occurrences per paragraph
- [X] T010 [US2] Implement boilerplate set computation: paragraphs where `count > threshold * len(texts)`
- [X] T011 [US2] Implement cleaned text assembly: filter paragraphs not in boilerplate set, rejoin with `\n\n`

**Checkpoint**: `remove_cross_page_boilerplate()` correctly identifies and removes high-frequency paragraphs across pages.

---

## Phase 3: Plugin Wiring (US1 + US2)

**Purpose**: Integrate cross-page dedup into the ingestion flow and handle documents emptied by cleanup.

**Independent Test**: Run a full ingest-website handle() with pages containing cross-page boilerplate. Verify boilerplate paragraphs are removed and empty documents are excluded before pipeline execution.

### Implementation

- [X] T012 [US2] Import `remove_cross_page_boilerplate` in plugins/ingest_website/plugin.py alongside existing `extract_text` and `extract_title` imports
- [X] T013 [US2] Add cross-page dedup call in `handle()` after document construction: extract texts, run `remove_cross_page_boilerplate()`, update document contents
- [X] T014 [US2] Add empty document filtering after cross-page dedup: `documents = [d for d in documents if d.content.strip()]`

**Checkpoint**: Full ingestion flow applies both HTML-level and cross-page cleanup. Empty documents do not reach the pipeline.

---

## Phase 4: Crawler URL Fix (US3)

**Purpose**: Record the final URL after HTTP redirects for accurate source citations and dedup.

**Independent Test**: Crawl a URL that redirects. Verify the returned dict contains the post-redirect URL.

### Implementation

- [X] T015 [US3] Change URL recording in `crawl()` in plugins/ingest_website/crawler.py from `normalized` to `_normalize_url(str(response.url))` and store as `final_url`
- [X] T016 [US3] Add comment explaining why `response.url` is used (final URL after redirects)

**Checkpoint**: Crawler returns post-redirect URLs for all pages.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (HTML Filtering)**: No dependencies -- start immediately
- **Phase 2 (Cross-Page Dedup)**: No dependencies -- can run in parallel with Phase 1 (different functions in same file)
- **Phase 3 (Plugin Wiring)**: Depends on Phase 2 (needs `remove_cross_page_boilerplate` to exist)
- **Phase 4 (Crawler URL Fix)**: No dependencies -- can run in parallel with all phases (different file)

### Parallel Opportunities

**Phase 1**: T001-T005 sequential (same function, same file, cumulative changes).
**Phase 2**: T006-T011 sequential (building one function incrementally).
**Phase 3**: T012-T014 sequential (building on each other in plugin.py).
**Phase 4**: T015-T016 parallel with all other phases (separate file: crawler.py).

---

## Phase 5: Tests

**Focus**: Validate all acceptance scenarios
**Dependencies**: Phases 1-4

### Implementation

- [X] T017 [P2] [US1] Test that `extract_text()` strips `aside`, `form`, `dialog`, `noscript` tags -- `tests/plugins/test_ingest_website.py`
- [X] T018 [P2] [US1] Test that `extract_text()` removes elements with cookie/consent/banner class/ID patterns -- `tests/plugins/test_ingest_website.py`
- [X] T019 [P2] [US2] Test `remove_cross_page_boilerplate()` removes paragraphs appearing on >50% of pages -- `tests/plugins/test_ingest_website.py`
- [X] T020 [P2] [US2] Test `remove_cross_page_boilerplate()` skips when fewer than `min_pages` pages -- `tests/plugins/test_ingest_website.py`
- [X] T021 [P2] [US2] Test that empty documents are filtered after cross-page dedup -- `tests/plugins/test_ingest_website.py`
- [X] T022 [P3] [US3] Test crawler records `response.url` (final URL after redirect) -- `tests/plugins/test_ingest_website.py`
- [X] T023 [P1] [US1] Test that semantic tag extraction (p, section, article, h1-h6) is unaffected by boilerplate removal (SC-004 regression) -- `tests/plugins/test_ingest_website.py`
- [X] T024 [P1] [US1] Test fallback to full text extraction still works after boilerplate stripping (SC-005) -- `tests/plugins/test_ingest_website.py`

**Checkpoint**: All acceptance scenarios verified. No regressions in semantic extraction or fallback behavior.

---

## Implementation Strategy

### Layer-by-Layer Delivery

1. Phase 1 -> HTML-level boilerplate stripped from extracted text
2. Phase 2 -> Cross-page dedup function implemented
3. Phase 3 -> Both layers wired into ingestion flow
4. Phase 4 -> Crawler URL accuracy fixed
5. **VALIDATE**: Ingest a real website and verify chunks are clean
