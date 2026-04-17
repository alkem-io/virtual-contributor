# Research: Website Content Quality Improvements

**Feature Branch**: `story/021-website-content-quality`
**Date**: 2026-04-15

## Research Tasks

### R1: Why regex for boilerplate detection (vs. ML, vs. readability libraries)

**Context**: Crawled websites frequently contain cookie banners, consent dialogs, newsletter popups, and other boilerplate that pollutes the knowledge base. We need to identify and remove these elements during HTML parsing.

**Findings**:

Three approaches were evaluated:

1. **ML-based classifiers** (e.g., trained models to classify DOM subtrees as boilerplate vs. content): High accuracy but adds a model dependency, increases inference time per page, requires training data, and introduces a provider dependency that violates P3 (No Vendor Lock-in). Overkill for this use case.

2. **Readability libraries** (e.g., `readability-lxml`, `trafilatura`): Extract "main content" by analyzing DOM structure. These work well for article-style pages but can over-strip on sites with non-article layouts (product pages, landing pages, documentation). They also replace the existing BeautifulSoup-based extraction pipeline rather than complementing it, introducing risk of regression.

3. **Regex on class/ID attributes**: Boilerplate UI components follow strong naming conventions in web development. Cookie banners are almost universally named with classes/IDs containing `cookie`, `consent`, `gdpr`, `banner`, etc. This approach is zero-dependency (stdlib `re`), fast, deterministic, and easy to extend.

**Decision**: Use regex matching on element class and ID attributes via `_BOILERPLATE_RE`.
**Rationale**: Covers the vast majority of real-world boilerplate with zero new dependencies, no model inference cost, and trivial maintenance (adding a new pattern is a one-line change). Aligns with AS:Simplicity (Simplicity Over Speculation).
**Alternatives considered**: ML classifiers (rejected -- overkill, vendor lock-in), readability libraries (rejected -- replaces rather than complements existing pipeline, regression risk).

---

### R2: Why cross-page dedup threshold at 50%

**Context**: Some boilerplate survives HTML-level filtering because it lives inside semantic tags (e.g., a company tagline in a `<p>` tag, a repeated CTA paragraph). Cross-page frequency analysis provides a second cleanup pass.

**Findings**:

The threshold determines how aggressively paragraphs are removed. Tested several values:

- **>25%**: Too aggressive. On a 20-page site, a paragraph appearing on 6 pages would be removed. Legitimate content like product descriptions or company mission statements can appear on 5-6 pages.
- **>50%**: Good balance. A paragraph must appear on more than half of all pages to be flagged. On a 20-page site, it must appear on 11+ pages. This strongly indicates site-wide boilerplate (footers, cookie text, legal disclaimers) rather than section-specific content.
- **>75%**: Too conservative. Boilerplate that appears on 60% of pages (e.g., present on all pages except a few special landing pages) would survive.

**Decision**: Use 50% threshold (`threshold=0.5`).
**Rationale**: Content appearing on more than half of all pages is overwhelmingly boilerplate. The strict-greater-than comparison (`count > cutoff`) means a paragraph must appear on a clear majority of pages. This balances false positives (removing legitimate content) against false negatives (keeping boilerplate).
**Alternatives considered**: 25% (too aggressive), 75% (too conservative), configurable env var (rejected -- adds config complexity for a parameter that rarely needs tuning).

---

### R3: Why min_pages=4 for cross-page dedup activation

**Context**: The cross-page dedup algorithm needs a minimum sample size to make meaningful frequency decisions.

**Findings**:

With 2-3 pages, the 50% threshold becomes unreliable:
- **2 pages**: A paragraph on both pages (100%) is removed, but on a 2-page site, repeated content (e.g., company name, contact info) is likely legitimate.
- **3 pages**: A paragraph on 2 of 3 pages (67%) is removed. On small sites, this is often a company description or product overview that legitimately appears on most pages.
- **4 pages**: A paragraph must appear on 3+ of 4 pages (75%+) to be removed. At this sample size, truly ubiquitous text is much more likely to be boilerplate than content.

**Decision**: Set `min_pages=4`. Below this threshold, cross-page dedup is skipped entirely.
**Rationale**: Small websites have high natural content overlap. Requiring 4+ pages ensures the frequency signal is meaningful. The `page_limit` default is 20, so most crawls will exceed this threshold.
**Alternatives considered**: min_pages=3 (rejected -- too aggressive on small sites), min_pages=5 (considered acceptable but 4 provides good coverage without being too restrictive).

---

### R4: Why paragraph-level dedup (not line-level)

**Context**: The cross-page dedup function splits text into units for comparison. The granularity of these units affects accuracy.

**Findings**:

- **Line-level** (split on `\n`): Too granular. Short lines like "Learn more" or "Read our blog" appear frequently but are not standalone boilerplate -- they depend on surrounding context. Line-level dedup would also catch common sentence patterns that happen to repeat.
- **Paragraph-level** (split on `\n\n`): Matches the output format of `extract_text()`, which joins semantic parts with `\n\n`. Each paragraph is a meaningful content unit (typically a `<p>` tag's content). A paragraph appearing on >50% of pages is a strong boilerplate signal.
- **Document-level**: Too coarse. Only detects fully duplicated pages, not repeated sections within otherwise unique pages.

The 20-character minimum length filter on paragraphs further prevents false positives from short, naturally repeated phrases.

**Decision**: Use paragraph-level splitting (split on `\n\n`) with 20-character minimum length.
**Rationale**: Paragraphs are the natural content unit produced by `extract_text()`. The granularity matches the semantic extraction output format, making the dedup a natural post-processing step.
**Alternatives considered**: Line-level (rejected -- too granular, high false positive rate), document-level (rejected -- too coarse, misses repeated sections).

---

### R5: Why final URL matters for dedup and source citations

**Context**: The crawler used the pre-redirect URL (`normalized`) as the document URL. When a site redirects (e.g., `/docs` to `/docs/en-US`), the stored URL does not match the actual page location.

**Findings**:

Two problems arise from using pre-redirect URLs:

1. **Source citations**: RAG answers include source URLs in responses. A pre-redirect URL may not resolve correctly for users, or may redirect to an unexpected page if the redirect target changes later.

2. **Content dedup**: The pipeline uses document URLs as document IDs (`document_id=page["url"]`). If two pre-redirect URLs point to the same final page, both get ingested as separate documents with identical content. Using the final URL ensures correct dedup via the ContentHashStep.

The httpx client is already configured with `follow_redirects=True`, so `response.url` contains the final URL after all redirect hops. The fix is a one-line change: use `_normalize_url(str(response.url))` instead of `normalized`.

**Decision**: Record `response.url` (post-redirect) instead of the pre-redirect URL.
**Rationale**: The final URL is what the user's browser would display. It is the canonical location of the content. Using it for both document ID and source citation ensures accuracy.
**Alternatives considered**: Recording both URLs (rejected -- adds complexity for no benefit; the pre-redirect URL is not useful once the content is fetched).

---

## Summary of Decisions

| Topic | Decision | Key Rationale |
|-------|----------|---------------|
| Boilerplate detection | Regex on class/ID attributes | Zero-dependency, deterministic, covers common naming conventions |
| Cross-page threshold | 50% of pages | Balances false positives and false negatives |
| Minimum pages | 4 pages to activate | Small sites have legitimate content overlap |
| Dedup granularity | Paragraph-level (split on `\n\n`) | Matches `extract_text()` output format, meaningful content units |
| URL tracking | Use `response.url` (post-redirect) | Accurate source citations, correct document dedup |
| Expanded strip tags | `aside`, `form`, `dialog`, `noscript` | Structural elements that never contain primary content |
