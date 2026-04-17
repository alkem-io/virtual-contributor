# Feature Specification: Website Content Quality Improvements

**Feature Branch**: `story/021-website-content-quality`
**Created**: 2026-04-15
**Status**: Implemented

## User Scenarios & Testing *(mandatory)*

### User Story 1 -- Knowledge Base Free of Cookie and Consent Boilerplate (Priority: P1)

As a knowledge base consumer, I want crawled website content to exclude cookie banners, consent dialogs, newsletter popups, and other boilerplate elements, so that RAG retrieval answers are not polluted with irrelevant text like "We use cookies to improve your experience" or "Subscribe to our newsletter."

**Why this priority**: Boilerplate text directly degrades answer quality. When a user asks a domain question, chunks containing cookie policy or newsletter signup text may score highly enough to be included in the LLM context window, displacing genuinely relevant content.

**Independent Test**: Ingest a website that has a cookie consent banner (e.g., one with a `<div class="cookie-banner">` element). Verify that no stored chunks contain cookie/consent/GDPR text. Compare with previous behavior where such text appeared in chunks.

**Acceptance Scenarios**:

1. **Given** HTML containing a `<div class="cookie-consent">Accept all cookies</div>`, **When** text extraction runs, **Then** the cookie consent text is excluded from the output.
2. **Given** HTML containing a `<dialog id="gdpr-modal">...</dialog>`, **When** text extraction runs, **Then** the dialog content is excluded.
3. **Given** HTML containing a `<form class="newsletter-subscribe">...</form>`, **When** text extraction runs, **Then** the form content is excluded.
4. **Given** HTML containing a `<div id="popup-signup">...</div>`, **When** text extraction runs, **Then** the popup content is excluded.
5. **Given** HTML with structural tags `<aside>`, `<noscript>`, **When** text extraction runs, **Then** those elements are stripped before semantic extraction.

---

### User Story 2 -- Cross-Page Boilerplate Deduplication (Priority: P2)

As a knowledge base consumer, I want repeated boilerplate paragraphs that appear across many pages of the same website to be automatically removed, so that the knowledge base does not contain dozens of identical paragraphs like "Company X is a leader in..." or "Contact us at support@example.com" that the HTML-level cleanup missed.

**Why this priority**: Some boilerplate survives HTML filtering because it lives inside semantic tags (e.g., a footer paragraph inside a `<p>` tag rendered via JavaScript). Cross-page frequency analysis catches what structural HTML filtering cannot.

**Independent Test**: Crawl a website with 5+ pages. Verify that paragraphs appearing on more than half the pages are removed from the final documents. Verify that unique page content is preserved.

**Acceptance Scenarios**:

1. **Given** 5 crawled pages where 4 contain the paragraph "Company X was founded in 2010...", **When** cross-page dedup runs, **Then** that paragraph is removed from all pages.
2. **Given** 3 crawled pages (below the min_pages=4 threshold), **When** cross-page dedup runs, **Then** all content is preserved unchanged (dedup does not activate).
3. **Given** a paragraph shorter than 20 characters appearing on all pages, **When** cross-page dedup runs, **Then** it is not considered for removal (too short to be meaningful boilerplate).
4. **Given** cross-page dedup removes all content from a page, **When** the document list is filtered, **Then** that empty document is dropped and does not enter the ingest pipeline.

---

### User Story 3 -- Accurate URL Tracking After Redirects (Priority: P3)

As a knowledge base consumer, I want stored document URLs to reflect the actual page location after HTTP redirects, so that source citations in RAG answers point to valid, accessible URLs rather than pre-redirect URLs that may not resolve correctly.

**Why this priority**: Incorrect source URLs in RAG answers undermine user trust. When a user clicks a source link and gets a redirect or 404, the answer loses credibility even if the content is correct.

**Independent Test**: Crawl a website where `/docs` redirects to `/docs/en-US`. Verify that the stored document URL is the final `/docs/en-US` URL, not the pre-redirect `/docs`.

**Acceptance Scenarios**:

1. **Given** a page at `/docs` that redirects to `/docs/en-US`, **When** the crawler records the page, **Then** the stored URL is the normalized form of `/docs/en-US`.
2. **Given** a page with no redirect, **When** the crawler records the page, **Then** the stored URL matches the requested URL (no behavioral change).

---

### Edge Cases

- When HTML-level boilerplate filtering removes all content from a page, the fallback to full `soup.get_text()` may still capture some content. The cross-page dedup layer provides a second cleanup pass.
- When a website has fewer than 4 pages, cross-page dedup is intentionally skipped because on small sites, repeated content is more likely to be legitimate (e.g., a 3-page site where the company description appears on 2 pages).
- When a boilerplate regex pattern matches a legitimate class name (e.g., a page about "cookie recipes" with `class="cookie-content"`), the content inside may be incorrectly stripped. This is an accepted trade-off; the regex patterns target UI component naming conventions, not content topics.
- When all documents become empty after cross-page dedup, the cleanup pipeline runs to remove previously stored chunks from the knowledge store.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The HTML parser MUST strip `aside`, `form`, `dialog`, and `noscript` elements in addition to the existing `script`, `style`, `nav`, `footer`, `header` elements.
- **FR-002**: The HTML parser MUST remove elements whose `class` or `id` attributes match boilerplate patterns (cookie, consent, banner, popup, modal, gdpr, newsletter, subscribe, sign-up, opt-in, privacy-notice, bottom-bar, snackbar).
- **FR-003**: Boilerplate element removal MUST occur before semantic tag extraction, so that boilerplate content inside semantic tags is also removed.
- **FR-004**: The system MUST provide a cross-page paragraph deduplication function that removes paragraphs appearing on more than 50% of crawled pages (strict greater-than: count > threshold x total_pages).
- **FR-005**: Cross-page dedup MUST only activate when 4 or more pages are crawled. Below that threshold, all content is preserved.
- **FR-006**: Cross-page dedup MUST ignore paragraphs shorter than 20 characters (after whitespace normalization).
- **FR-007**: Cross-page dedup MUST use case-insensitive, whitespace-normalized comparison to match paragraphs.
- **FR-008**: Documents that become empty after cross-page dedup MUST be excluded from the ingest pipeline.
- **FR-009**: The crawler MUST record the final URL after HTTP redirects (from `response.url`) instead of the pre-redirect URL.

### Key Entities

- **_STRIP_TAGS**: Extended list of HTML elements removed before text extraction.
- **_BOILERPLATE_RE**: Compiled regex pattern matching boilerplate class/ID naming conventions.
- **remove_cross_page_boilerplate()**: Function that performs paragraph-level frequency analysis across pages and strips high-frequency paragraphs.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Websites with cookie consent banners produce zero chunks containing cookie/consent/GDPR text after ingestion.
- **SC-002**: Repeated boilerplate paragraphs across 4+ pages are eliminated, reducing chunk duplication in the knowledge store.
- **SC-003**: Source URLs in RAG answers point to the actual page location (post-redirect), not the pre-redirect URL.
- **SC-004**: No regression in extraction of legitimate page content -- semantic extraction still captures p, section, article, h1-h6, title, li tags.
- **SC-005**: The fallback to full text extraction (when semantic extraction yields < 3 parts) still functions after boilerplate removal.

## Assumptions

- Boilerplate elements follow common web development naming conventions for CSS classes and IDs (e.g., `cookie-banner`, `gdpr-modal`, `newsletter-popup`). Sites using non-standard naming will not be caught by HTML-level filtering but may still be caught by cross-page dedup.
- The 50% threshold for cross-page dedup is appropriate for most websites. A paragraph appearing on more than half of all crawled pages is overwhelmingly likely to be boilerplate rather than legitimate content.
- The minimum 4-page threshold prevents false positives on small websites where content naturally repeats across pages.
- The `response.url` attribute from httpx correctly reflects the final URL after all redirects when `follow_redirects=True` is set.

### Non-Functional Requirements

- **NFR-001**: Boilerplate filtering adds negligible processing time relative to crawl and LLM operations. No performance targets required.
