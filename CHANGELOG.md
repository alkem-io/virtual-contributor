# CHANGELOG


## v0.1.1 (2026-04-27)

### Bug Fixes

- **ci**: Use bot token for checkout to allow pushing to main
  ([`89db36d`](https://github.com/alkem-io/virtual-contributor/commit/89db36d053be27633fc2a96edc89ef0dbf107a83))

The checkout action sets git remote auth — must use the bot token so semantic-release can push the
  version bump commit and tag.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- **ci**: Use org infrastructure bot token for semantic release
  ([`7440b84`](https://github.com/alkem-io/virtual-contributor/commit/7440b844c15bc42c843a42765d7987321e5084b0))

Replace RELEASE_TOKEN with ALKEMIO_INFRASTRUCTURE_BOT_PUSH_TOKEN, the org-level PAT already
  available across alkem-io repositories.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Chores

- Revert version to 0.1.0
  ([`e5c00b7`](https://github.com/alkem-io/virtual-contributor/commit/e5c00b7e01e1c777e8b7997fa05a95093807dbee))

Let semantic-release determine the version from commit history.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>


## v0.1.0 (2026-04-23)

### Bug Fixes

- Address CodeRabbit review comments on RAG evaluation framework
  ([#38](https://github.com/alkem-io/virtual-contributor/pull/38),
  [`767cac5`](https://github.com/alkem-io/virtual-contributor/commit/767cac5af9ac025bebccb0104cf04dfec28e9142))

- runner.py: normalize nan/inf scores, sanitize label for filesystem-safe run IDs, separate
  invoke/score try blocks to preserve pipeline output on scoring failure, use asyncio.to_thread for
  synchronous RAGAS evaluate() - cli.py: cleanup invoker on setup failure, graceful error handling
  in compare command for malformed run files - generator.py: raise ClickException on empty
  collection, pre-validate before TestCase construction, extract source URIs from metadata instead
  of collection name, use meaningful query instead of empty string - report.py: accept optional
  output_path in format_run_summary - .gitignore: use evaluations/* pattern for proper .gitkeep
  re-include - docs: update ADR references to 0006, fix test case count, add language tags to fenced
  code blocks

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Address CodeRabbit review findings in pipeline engine
  ([`4ad8bd3`](https://github.com/alkem-io/virtual-contributor/commit/4ad8bd3b1a6587f3b92cdbbdff3540f9daebc0b7))

- Reject finalize_steps in sequential mode (silent no-op) - Populate all_document_ids in sequential
  mode for correct ChangeDetection behavior - Don't double-store BoK chunk after inline persist
  succeeds - Fix test fixture embeddingType to match _bok_exists query

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Clean up stale summaries and BoK on edge cases
  ([#72](https://github.com/alkem-io/virtual-contributor/pull/72),
  [`2fe211d`](https://github.com/alkem-io/virtual-contributor/commit/2fe211ddb7a2393641739cedd0c1180069aa9ea1))

* fix: clean up stale per-document summaries and BoK entry on edge cases

When a document drops below the summary chunk threshold after re-ingest, its orphaned summary entry
  now gets marked for deletion. When the entire corpus becomes empty due to document removals, the
  BoK summary entry is similarly cleaned up. Closes #36.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: rewrite SDD artifacts to follow SpecKit templates for story #36

Move spec/plan/tasks/clarifications from root-level freeform files into
  specs/013-summary-lifecycle-management/ with proper SpecKit template formatting. All 7 required
  artifacts created: spec.md, plan.md, tasks.md, research.md, data-model.md, quickstart.md, and
  checklists/requirements.md.

* fix: address CodeRabbit MD040 lint findings for story #36

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Consistent summarization behavior between ingest-website and ingest-space
  ([#77](https://github.com/alkem-io/virtual-contributor/pull/77),
  [`776882c`](https://github.com/alkem-io/virtual-contributor/commit/776882c4b94cfe7dde4b3f31a57a51273f17dd9f))

* fix: consistent summarization behavior between ingest-website and ingest-space

Both ingest plugins now honor a shared `summarize_enabled` config flag (default true) and treat
  `summarize_concurrency=0` as sequential (mapped to 1) rather than disabling summarization. Removes
  inline BaseConfig() from ingest-website handle() in favor of constructor injection.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: rewrite SDD artifacts to follow SpecKit templates for story alkemio#1827

Move artifacts from docs/stories/1827/ to specs/018-consistent-summarization/ with proper formatting
  matching specs/010-bok-llm-factory-hardening/ reference. All 7 required artifacts created (spec,
  plan, tasks, research, data-model, quickstart, checklists/requirements) with all tasks marked [X].

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Document processing reliability, source attribution, and retrieval alignment
  ([#31](https://github.com/alkem-io/virtual-contributor/pull/31),
  [`739e0ad`](https://github.com/alkem-io/virtual-contributor/commit/739e0ad04fb1306e547c8ba507f11547156120c0))

* Refines document processing and LLM interactions

Enhances LLM adapter reliability by adding a retry mechanism for API calls.

Improves search result context by sorting retrieved documents by relevance, deduplicating results by
  source URL, and limiting the number of unique sources returned. Also standardizes source URIs.

Makes document summarization steps within the ingestion pipeline configurable and optional based on
  system settings, allowing for flexible resource management.

* fix: align pipeline with original repo — prompts, summary length, chunk IDs

- Prompts: adopt original repo's detailed FORMAT/REQUIREMENTS/FORBIDDEN structure for both document
  and BoK summarization - Summary length: change default from 2,000 to 10,000 chars to match
  original repo's SUMMARY_LENGTH - Chunk documentId: StoreStep now writes "{id}-chunk{index}" format
  to ChromaDB metadata, matching original repo convention. The transform happens at storage time so
  DocumentSummaryStep grouping still works on the original document_id.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* Enhances async robustness and message handling

Moves synchronous LLM calls to a thread to prevent blocking the event loop, ensuring stable RabbitMQ
  heartbeats. Configures RabbitMQ with heartbeats and TCP keepalive for more resilient connections.

Adds a retry mechanism for failed RabbitMQ messages, preventing data loss from transient errors.

Changes document summarization to sequential processing, simplifying error handling and improving
  stability.

* fix: enhances async robustness and message handling

* fix: restore source attribution, filtering, and dedup from original engines

- Add [source:N] prefix formatting to guidance and expert plugins, matching original
  combine_query_results() behavior (#7) - Add configurable score-threshold filtering (default 0.3)
  to exclude low-relevance chunks before LLM prompt assembly (#8) - Reduce expert n_results from 10
  to 5 (configurable via RETRIEVAL_N_RESULTS env var) to prevent context overload (#9) - Deduplicate
  expert sources by source URL, matching original {doc["source"]: doc}.values() pattern - Fix LLM
  adapter tests to mock sync invoke() instead of async ainvoke() - Add spec artifacts for feature
  005-fix-document-reliability

* fix: address CodeRabbit review — type safety, retry, validation, dedup

- rabbitmq.py: narrow retry_count to int, replace message.process() context manager with explicit
  ack()/reject(), capture exchange for type narrowing, wrap retry publish in try/except - config.py:
  add validation guards for rabbitmq_heartbeat >= 0 and rabbitmq_max_retries >= 1 -
  provider_factory.py: set max_retries=0 to prevent multiplicative retries (adapter already retries
  3x with backoff) - guidance/plugin.py: use unique fallback key for None sources in dedup

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Fill missing required fields with type defaults in PromptGraph (spec 029)
  ([#90](https://github.com/alkem-io/virtual-contributor/pull/90),
  [`3d781b2`](https://github.com/alkem-io/virtual-contributor/commit/3d781b24e293a2c6cc873bf734be44abc33b6aad))

* fix: fill missing required fields with type defaults in PromptGraph recovery

Small LLMs (e.g. Mistral-Small) sometimes drop auxiliary required fields from structured output.
  Instead of aborting the entire response, fill missing fields with type-appropriate defaults and
  log a warning.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* docs: correct test count from 7 to 6 in spec artifacts

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Fixed existing bok check
  ([`d0a5e65`](https://github.com/alkem-io/virtual-contributor/commit/d0a5e65c02b20a44d237df62ae822279a54a89a4))

- Introduces configurable LLM call timeouts
  ([`ab3f9d7`](https://github.com/alkem-io/virtual-contributor/commit/ab3f9d7da652678dc5c52c577f60608a803f185e))

Prevents LLM calls from hanging indefinitely by allowing a maximum duration for `ainvoke`
  operations. Configures a timeout for LangChain LLM adapter calls, sourced from the `llm_timeout`
  setting. Implements retries for `asyncio.TimeoutError` exceptions.

- Pass pre-computed embeddings through ChromaDB adapter
  ([#3](https://github.com/alkem-io/virtual-contributor/pull/3),
  [`b207c60`](https://github.com/alkem-io/virtual-contributor/commit/b207c600544962ed9f40653cb69b04c8f69486e5))

* Integrates OpenAI Assistant and refines JSON parsing

Adds a new adapter for OpenAI Assistants, making it available for interacting with the OpenAI API.

Enhances the Guidance plugin's JSON parsing to strip markdown code fences from LLM responses,
  improving robustness when extracting structured data.

Optimizes the Dockerfile build process by preventing the root package from being installed during
  Poetry dependency resolution, leading to leaner images.

* fix: pass pre-computed embeddings through ChromaDB adapter and ingest pipeline

ChromaDB's default embedding function requires onnxruntime, which is not installed. This change
  threads externally-computed embeddings (from ScalewayEmbeddingsAdapter) through the knowledge
  store port so ChromaDB collections are created with embedding_function=None and pre-computed
  vectors are passed directly via upsert/query.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: address CodeRabbit review feedback

- Enforce embeddings requirement in ChromaDBAdapter: raise ValueError when embeddings provider or
  precomputed embeddings are missing, since collections use embedding_function=None - Skip batches
  with incomplete embeddings in ingest pipeline instead of silently downgrading to embeddings=None -
  Guard _parse_json_sources against non-string input

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Promptgraph robustness & expert plugin integration
  ([#84](https://github.com/alkem-io/virtual-contributor/pull/84),
  [`97f5006`](https://github.com/alkem-io/virtual-contributor/commit/97f50064842601c15504a70adaca176d3f5289a4))

* chore: enhances space ingestion with cleaning and deduplication

Injects a GraphQL client for the ingest-space plugin, configured via settings or environment
  variables, to enable API queries.

Rewrites the space tree reader for robust content extraction from the Alkemio hierarchy. Integrates
  HTML stripping and content normalization for cleaner, consistent documents. Implements content
  deduplication to prevent redundant documents and improves overall data quality. Updates the
  GraphQL query and processing logic for various content types like spaces, callouts, posts,
  whiteboards, and links.

* fix: make PromptGraph robust against real-world Alkemio schemas and LLM output

Adds schema normalization (list→dict properties), nullable field handling, structured output
  recovery from malformed LLM responses, and Pydantic model state compatibility. Fixes expert plugin
  to use correct state keys, populate conversation history, and prefer rephrased questions for
  retrieval.

Includes SDD spec 023 artifacts and 25 new unit tests.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: resolve lint F402 shadow and fix pre-existing test_ingest_space failures

Rename `field` loop variable to `finfo` in _recover_fields to avoid shadowing the dataclass `field`
  import (ruff F402). Fix 3 existing test_ingest_space tests: add missing `seen` parameter and
  update callout data structure to `calloutsSet.callouts`.

* fix: address CodeRabbit review — single LLM call recovery, GraphQL guard, test fixture

Restructure _make_chain_node to invoke LLM once then parse, avoiding double LLM call on structured
  output failure. Require admin_password for GraphQL client construction. Fix collaboration fixture
  shape in test_process_space_extracts_description.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Publish error response only on final retry attempt
  ([#85](https://github.com/alkem-io/virtual-contributor/pull/85),
  [`734ecc2`](https://github.com/alkem-io/virtual-contributor/commit/734ecc28ff01e1d42c5368049a3a91d4560d17db))

* chore: enhances space ingestion with cleaning and deduplication

Injects a GraphQL client for the ingest-space plugin, configured via settings or environment
  variables, to enable API queries.

Rewrites the space tree reader for robust content extraction from the Alkemio hierarchy. Integrates
  HTML stripping and content normalization for cleaner, consistent documents. Implements content
  deduplication to prevent redundant documents and improves overall data quality. Updates the
  GraphQL query and processing logic for various content types like spaces, callouts, posts,
  whiteboards, and links.

* fix: publish error response only on final retry to avoid chat spam

Consolidates error response publishing into _retry_or_reject and suppresses intermediate retry
  failures. Only the last exhausted attempt publishes an error message so users get a single clear
  error instead of one per retry.

Includes SDD spec 024 artifacts.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: fix pre-existing test_ingest_space failures

Fix 3 existing test_ingest_space tests: add missing `seen` parameter and update callout data
  structure to `calloutsSet.callouts`.

* fix: address CodeRabbit review — republish fallback, GraphQL guard, spec wording

Publish error response when republish_with_headers fails so users aren't left hanging. Require
  admin_password for GraphQL client. Fix test fixture shape and relax SC-003 wording.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Remove hardcoded distance score filter from guidance plugin
  ([`6cd7630`](https://github.com/alkem-io/virtual-contributor/commit/6cd76302cbe042ece5e2554a773a6d50324e3388))

The original virtual-contributor-engine-guidance repo passed ALL retrieved documents to the LLM
  without distance filtering. The 0.3 score threshold added during migration silently dropped all
  results when using embedding models with L2 distances > 0.7 (e.g., qwen3-embed produces distances
  of 0.9-1.2 for relevant results).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Retrospec skill creates worktrees per spec, not just directories
  ([`e97be2b`](https://github.com/alkem-io/virtual-contributor/commit/e97be2b692d6ef65b8636ff7cad88c570a57f70a))

The worktree-isolation principle was contradicted by "Do NOT create feature branches." Now Step 4
  creates a git worktree + branch per spec and applies only that spec's code changes. Parallel
  subagents handle concurrent worktree setup.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Run cleanup pipeline on empty corpus re-ingestion
  ([#75](https://github.com/alkem-io/virtual-contributor/pull/75),
  [`e2cf09f`](https://github.com/alkem-io/virtual-contributor/commit/e2cf09f56133551508c8048af6a85702b6f66c7e))

* fix: run cleanup pipeline on empty corpus re-ingestion (#35)

When a fetch succeeds but returns zero documents, both ingest plugins now run ChangeDetectionStep +
  OrphanCleanupStep to remove stale chunks instead of returning early and leaving orphaned data
  queryable.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: rewrite SDD artifacts to follow SpecKit templates for story #35

Move freeform root-level spec.md, plan.md, tasks.md into specs/012-empty-corpus-reingestion/ with
  proper SpecKit formatting. Add all 7 required artifacts: spec.md, plan.md, tasks.md, research.md,
  data-model.md, quickstart.md, and checklists/requirements.md.

* fix: address CodeRabbit review findings on PR #75

1. CRITICAL: Crawl errors now raise CrawlError on base URL failure instead of returning [],
  preventing transient network failures from triggering cleanup that purges all stored content.
  Subsequent page errors still continue gracefully.

2. MAJOR: ChangeDetectionStep now records store-read errors in context.errors so the cleanup
  pipeline correctly reports failure when it cannot read existing chunks (instead of silently
  becoming a no-op).

3. Minor: Spec acceptance scenarios now clarify that BoK summary cleanup is out of scope (references
  Edge Cases section).

4. Minor: FR-003/FR-004 updated to reflect actual per-plugin result types (IngestionResult enum for
  website, plain string for space).

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Skip upsert for unchanged chunks in StoreStep
  ([#71](https://github.com/alkem-io/virtual-contributor/pull/71),
  [`4f29ba2`](https://github.com/alkem-io/virtual-contributor/commit/4f29ba2f11cda8fd16b7f280afc07bfda74c96ec))

* fix: skip upsert for unchanged chunks in StoreStep

StoreStep now filters out chunks whose content_hash is in context.unchanged_chunk_hashes before
  calling ingest(), avoiding redundant writes to ChromaDB on incremental updates. This reduces
  vector store I/O by up to 98% when most content is unchanged.

Closes alkem-io/alkemio#1825

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: rewrite SDD artifacts to follow SpecKit templates for story alkemio#1825

* fix: address CodeRabbit findings on spec artifacts for story alkemio#1825

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Chores

- Adds Git worktree management
  ([`bdc7fc4`](https://github.com/alkem-io/virtual-contributor/commit/bdc7fc47e1aaa96a063dc5e6a68cf92ee67e2ccd))

Introduces commands and skills for creating and removing Git worktrees. Automates worktree creation
  with new branches and opens a dedicated tmux pane. Implements guided removal, prompting for
  confirmation, closing tmux panes, and offering to delete the local branch.

- Set version to 1.0.0
  ([`2f349ca`](https://github.com/alkem-io/virtual-contributor/commit/2f349ca5f7e4442b4ffce48cf00e1614f8e0c7e2))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Stage pending changes and fix duplicate disable_thinking block
  ([`2adac30`](https://github.com/alkem-io/virtual-contributor/commit/2adac30c75c276c3497d5fb0b3a804e96647276a))

Remove duplicate disable_thinking block in provider_factory (merge artifact). Include specs/008 PRD.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Update README and docs
  ([`3c28440`](https://github.com/alkem-io/virtual-contributor/commit/3c284400eb82f558b719bcc8d214ad9369115eee))

### Continuous Integration

- Automated semantic release pipeline (spec 030)
  ([#91](https://github.com/alkem-io/virtual-contributor/pull/91),
  [`456759c`](https://github.com/alkem-io/virtual-contributor/commit/456759c2a9de6b058ec647d4416db7129817107d))

Add python-semantic-release workflow on push to main, split build.yml into dual-registry auth
  (Docker Hub for releases, ghcr.io for dev), configure semantic_release in pyproject.toml, and
  document conventional commit conventions in CLAUDE.md.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Documentation

- Add SDD spec 021 — website content quality
  ([#81](https://github.com/alkem-io/virtual-contributor/pull/81),
  [`54e8d0e`](https://github.com/alkem-io/virtual-contributor/commit/54e8d0e23aee3c078656c9e6b07b419690b61734))

Adds full SDD artifact set for website content quality improvements: HTML boilerplate removal,
  cross-page deduplication, and redirect URL tracking.

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Sdd spec 019 — batched ingest pipeline
  ([#79](https://github.com/alkem-io/virtual-contributor/pull/79),
  [`5e72243`](https://github.com/alkem-io/virtual-contributor/commit/5e722437740875137d31a97a1526ef738fc150ac))

* docs: add SDD spec 019 — batched ingest pipeline

Adds full SDD artifact set for the batched ingest pipeline feature: spec, plan, research,
  data-model, quickstart, tasks, and checklist.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* docs: fix BoKSummaryStep → BodyOfKnowledgeSummaryStep in quickstart

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Sdd spec 020 — pipeline reliability and BoK resilience
  ([#80](https://github.com/alkem-io/virtual-contributor/pull/80),
  [`696a764`](https://github.com/alkem-io/virtual-contributor/commit/696a7642338bf4e07431ee4d84d56cc68045a7dc))

* docs: add SDD spec 020 — pipeline reliability and BoK resilience

Adds full SDD artifact set for pipeline reliability improvements: async deadlock fix, BoK partial
  fallback, inline persistence, and section grouping.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* docs: fix backward-compatible hyphenation in plan

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Sdd spec 026 — link document extraction
  ([#87](https://github.com/alkem-io/virtual-contributor/pull/87),
  [`5ca95e7`](https://github.com/alkem-io/virtual-contributor/commit/5ca95e778d3f7751ed04f8c699ea9681ebe5dbbe))

* feat: fetch linked documents and extract text during space ingest

Links in space contributions now have their bodies fetched (with auth) and text extracted (PDF,
  DOCX, XLSX, HTML) so the actual referenced content becomes searchable, not just the URL metadata.

Also switches document and BoK summarization from sequential refine to parallel map-reduce for
  better throughput and quality on large corpora.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* docs: SDD spec 026 — link document extraction

Retrospec artifacts (spec, plan, research, data-model, quickstart, tasks, checklist) plus unit tests
  for link_extractor, graphql_client fetch_url/URI rewriting, and updated space_reader async tests.

* fix: address CI failures and CodeRabbit findings

- Remove unused refine prompt imports from steps.py - Handle empty map-reduce results as errors in
  DocumentSummaryStep - Narrow URI rewriting to known Alkemio hosts only - Only send auth token to
  Alkemio host, not arbitrary URLs - Case-insensitive magic byte sniffing in link_extractor - Update
  spec docs to reflect test coverage

* docs: add language tags to fenced code blocks in quickstart

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Sdd spec 027 — map-reduce summarization
  ([#88](https://github.com/alkem-io/virtual-contributor/pull/88),
  [`08541a9`](https://github.com/alkem-io/virtual-contributor/commit/08541a9d1ec99b0f0e7f5c4eb40529b858ef3f95))

* feat: fetch linked documents and extract text during space ingest

Links in space contributions now have their bodies fetched (with auth) and text extracted (PDF,
  DOCX, XLSX, HTML) so the actual referenced content becomes searchable, not just the URL metadata.

Also switches document and BoK summarization from sequential refine to parallel map-reduce for
  better throughput and quality on large corpora.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* docs: SDD spec 027 — map-reduce summarization

Retrospec artifacts (spec, plan, research, data-model, quickstart, tasks, checklist) plus unit tests
  for _map_reduce_summarize, split-model wiring on DocumentSummaryStep and
  BodyOfKnowledgeSummaryStep.

* fix: address CI failures and CodeRabbit findings

- Remove unused refine prompt imports from steps.py - Handle empty map-reduce results as errors in
  DocumentSummaryStep - Guard reduce_fanin < 2 to prevent infinite reduce loops - Narrow URI
  rewriting to known Alkemio hosts only - Only send auth token to Alkemio host, not arbitrary URLs -
  Migrate test_ingest_space.py to async _process_space signature - Remove unused imports from
  test_map_reduce.py - Add test for reduce_fanin validation

* docs: update spec docs to reflect test coverage

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Features

- Add speckit infrastructure and project constitution
  ([`76e259a`](https://github.com/alkem-io/virtual-contributor/commit/76e259a9ff3b5e3e8cb412d912427dd58f3234a2))

- Initialize .specify/ with templates, scripts, and memory - Create constitution defining
  Microkernel + Hexagonal Architecture principles - Fix PRD authorship attribution

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Async performance optimizations ([#5](https://github.com/alkem-io/virtual-contributor/pull/5),
  [`75ff90c`](https://github.com/alkem-io/virtual-contributor/commit/75ff90c36b4cd87c6a9cec54e0691c6efff3caf5))

* feat: async performance optimizations — parallel I/O, connection reuse, merged loops

- Parallelize summarization across documents and collection queries with asyncio.gather - Reuse
  httpx.AsyncClient across retries in embeddings adapter and GraphQL client - Merge embed + store
  loops into single iteration in ingest pipeline - Pre-build chunk lookup dict to avoid O(n²)
  per-document scan - Make DNS resolution non-blocking with asyncio.to_thread in crawler

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* Enhances async summarization and LLM connection stability

Introduces configurable concurrency (default 8) for document summarization during ingestion to
  prevent overwhelming LLM servers and improve batch processing speed. Refines summarization logic
  to only apply to multi-chunk documents.

Disables HTTP keep-alive connections for LLM clients when a custom `llm_base_url` is configured.
  This addresses stale connection issues common with local or self-hosted LLM servers that may close
  idle connections prematurely.

Updates the asynchronous performance optimization specification to reflect these changes, including
  new acceptance criteria and functional requirements.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Bok LLM, summarize base URL, and LLM factory hardening
  ([#55](https://github.com/alkem-io/virtual-contributor/pull/55),
  [`5cb2a7b`](https://github.com/alkem-io/virtual-contributor/commit/5cb2a7bd270da17db80b949b45dce14070c7ccd2))

* Adds speckit retrospec command definition

Introduces the `speckit.retrospec` command, designed to automatically generate single-responsibility
  SDD specifications from current code changes. It analyzes diffs, decomposes modifications into
  cohesive concerns, and produces a complete set of documentation artifacts (spec, plan, research,
  data model, etc.) for each, ensuring retrospective design clarity and consistency.

* feat: BoK LLM, summarize base URL, and LLM factory hardening

Add dedicated BoK LLM tier for large-context body-of-knowledge summarization (falls back to
  summarize LLM, then main LLM). Support SUMMARIZE_LLM_BASE_URL for local model servers. Harden LLM
  factory with disable_thinking for Qwen3 and Mistral-only keepalive fix.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: BoK validation, provider-guard extra_body, remove redundant import

- Add BoK LLM temperature/timeout validation and partial-config warning matching the existing
  summarize LLM pattern - Guard extra_body (disable_thinking) to OpenAI provider only, since
  ChatMistralAI and ChatAnthropic don't support it - Remove redundant _create_bok alias import,
  reuse existing create_llm_adapter

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Composable ingest pipeline engine ([#6](https://github.com/alkem-io/virtual-contributor/pull/6),
  [`d090cc0`](https://github.com/alkem-io/virtual-contributor/commit/d090cc0a486d49323944ee95cec491b62bfb3af6))

* feat: composable ingest pipeline engine with independently testable steps

Replace the monolithic run_ingest_pipeline() with a composable IngestEngine that executes
  PipelineStep instances in sequence. This fixes the critical correctness bug where document
  summaries overwrote chunk embeddings — EmbedStep now always embeds chunk.content, with summaries
  stored as separate entries.

New pipeline steps: ChunkStep, DocumentSummaryStep, BodyOfKnowledgeSummaryStep, EmbedStep,
  StoreStep. Includes step-level error boundaries, embedding safety guard in StoreStep, accurate
  chunks_stored tracking, and FR-006-compliant rich summarization prompts.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: address CodeRabbit review — embedding_type filtering, StoreStep simplification, test cleanup

- Replace endswith("-summary") heuristic in BoKSummaryStep with embedding_type != "summary" check to
  avoid ID collisions with real documents whose IDs end in "-summary" - Simplify StoreStep to always
  require precomputed embeddings — the ChromaDB adapter rejects embeddings=None, so the "no
  EmbedStep" path was dead code masking a runtime error - Remove duplicate tests
  (test_collection_replacement, test_pipeline_composition) - Fix metrics test to actually capture
  and assert on context.metrics - Update spec artifacts to reflect behavioral changes

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Configurable summarization LLM, retrieval params, and chunk threshold
  ([#34](https://github.com/alkem-io/virtual-contributor/pull/34),
  [`f469ce8`](https://github.com/alkem-io/virtual-contributor/commit/f469ce8126f85b37bf8901e649e48a2d552e63e0))

* feat: configurable summarization LLM, per-plugin retrieval params, and chunk threshold

Add environment-variable-driven configuration for three capabilities:

1. Separate summarization LLM (SUMMARIZE_LLM_PROVIDER/MODEL/API_KEY) — use a cheaper model for
  document/BoK summarization during ingestion while keeping the main LLM for user-facing responses.
  Falls back to main LLM when unconfigured.

2. Per-plugin retrieval parameters (EXPERT_N_RESULTS, EXPERT_MIN_SCORE, GUIDANCE_N_RESULTS,
  GUIDANCE_MIN_SCORE, MAX_CONTEXT_CHARS) — tune retrieval per plugin via env vars without code
  changes. Context budget enforcement drops lowest-scoring chunks when total chars exceed the
  budget.

3. Configurable chunk threshold (SUMMARY_CHUNK_THRESHOLD) — control the minimum chunk count before
  document summarization triggers. Default 4 with >= preserves existing > 3 behavior (FR-009
  backward compatibility).

All changes are additive — no port/adapter interface changes. 38 new tests added, 256 total pass.
  Ruff clean, pyright 0 errors.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: address CodeRabbit review feedback

- Validate chunk_threshold >= 1 at DocumentSummaryStep construction time - Fix dropped_chars
  calculation in ExpertPlugin to use raw content lengths - Add max_context_chars boundary validation
  tests (zero, negative) - Fix data-model.md: ExpertPlugin section now documents max_context_chars -
  Fix research.md: R5 context default corrected from 3 to 4 - Fix spec.md: FR-006 reworded for
  per-plugin budget enforcement, clarification section aligned with FR-011 DEBUG level for token
  logging

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Configurable vector DB distance function
  ([#54](https://github.com/alkem-io/virtual-contributor/pull/54),
  [`70ca004`](https://github.com/alkem-io/virtual-contributor/commit/70ca004f3bdeababb6fcf20c7201fb0cb11ad315))

* Adds speckit retrospec command definition

Introduces the `speckit.retrospec` command, designed to automatically generate single-responsibility
  SDD specifications from current code changes. It analyzes diffs, decomposes modifications into
  cohesive concerns, and produces a complete set of documentation artifacts (spec, plan, research,
  data model, etc.) for each, ensuring retrospective design clarity and consistency.

* feat: configurable vector DB distance function

Add VECTOR_DB_DISTANCE_FN environment variable to configure the ChromaDB HNSW distance metric
  (cosine, l2, ip). Validated at startup, passed to all get_or_create_collection calls. Defaults to
  cosine for backward compatibility.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: add distance_fn metadata to delete method for consistency

The delete method's get_or_create_collection call was missing the hnsw:space metadata that query,
  ingest, and get already pass.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Content-hash deduplication and orphan cleanup
  ([#32](https://github.com/alkem-io/virtual-contributor/pull/32),
  [`5b390ab`](https://github.com/alkem-io/virtual-contributor/commit/5b390abae7d7cd67fbdf74e26ede3794f5d1154b))

* Refines document processing and LLM interactions

Enhances LLM adapter reliability by adding a retry mechanism for API calls.

Improves search result context by sorting retrieved documents by relevance, deduplicating results by
  source URL, and limiting the number of unique sources returned. Also standardizes source URIs.

Makes document summarization steps within the ingestion pipeline configurable and optional based on
  system settings, allowing for flexible resource management.

* fix: align pipeline with original repo — prompts, summary length, chunk IDs

- Prompts: adopt original repo's detailed FORMAT/REQUIREMENTS/FORBIDDEN structure for both document
  and BoK summarization - Summary length: change default from 2,000 to 10,000 chars to match
  original repo's SUMMARY_LENGTH - Chunk documentId: StoreStep now writes "{id}-chunk{index}" format
  to ChromaDB metadata, matching original repo convention. The transform happens at storage time so
  DocumentSummaryStep grouping still works on the original document_id.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* Enhances async robustness and message handling

Moves synchronous LLM calls to a thread to prevent blocking the event loop, ensuring stable RabbitMQ
  heartbeats. Configures RabbitMQ with heartbeats and TCP keepalive for more resilient connections.

Adds a retry mechanism for failed RabbitMQ messages, preventing data loss from transient errors.

Changes document summarization to sequential processing, simplifying error handling and improving
  stability.

* fix: enhances async robustness and message handling

* fix: restore source attribution, filtering, and dedup from original engines

- Add [source:N] prefix formatting to guidance and expert plugins, matching original
  combine_query_results() behavior (#7) - Add configurable score-threshold filtering (default 0.3)
  to exclude low-relevance chunks before LLM prompt assembly (#8) - Reduce expert n_results from 10
  to 5 (configurable via RETRIEVAL_N_RESULTS env var) to prevent context overload (#9) - Deduplicate
  expert sources by source URL, matching original {doc["source"]: doc}.values() pattern - Fix LLM
  adapter tests to mock sync invoke() instead of async ainvoke() - Add spec artifacts for feature
  005-fix-document-reliability

* fix: address CodeRabbit review — type safety, retry, validation, dedup

- rabbitmq.py: narrow retry_count to int, replace message.process() context manager with explicit
  ack()/reject(), capture exchange for type narrowing, wrap retry publish in try/except - config.py:
  add validation guards for rabbitmq_heartbeat >= 0 and rabbitmq_max_retries >= 1 -
  provider_factory.py: set max_retries=0 to prevent multiplicative retries (adapter already retries
  3x with backoff) - guidance/plugin.py: use unique fallback key for None sources in dedup

* docs: add spec, plan, and tasks for content-hash dedup feature (006)

Full SDD artifacts for content-hash deduplication and orphan cleanup: spec.md, plan.md, tasks.md,
  research.md, data-model.md, quickstart.md, and knowledge-store-port contract. Includes
  post-analyze remediation fixes for FR-009 field alignment, FR-010 serialization clarification, and
  edge case coverage.

* feat: implement content-hash deduplication and orphan cleanup (#006)

Converts the ingestion pipeline from destructive delete-and-rebuild to incremental upsert with
  SHA-256 content-hash deduplication. Unchanged chunks skip re-embedding entirely (100% skip rate on
  unchanged corpora), orphaned chunks from changed chunking parameters are automatically cleaned up,
  and removed documents have all their chunks (including summaries) purged from the store.

Key changes: - Extend KnowledgeStorePort with get() and delete() methods - Add ContentHashStep,
  ChangeDetectionStep, OrphanCleanupStep - Modify StoreStep to use content-hash IDs for content
  chunks - Skip summarization for unchanged documents via change_detection_ran flag - Remove
  delete_collection() calls from both ingestion plugins - 252 tests passing, ruff clean, no new
  pyright errors

* chore: trigger CodeRabbit review

* fix: address CodeRabbit review — orphan detection, spec accuracy

- Mark documents with orphans as changed so summaries regenerate when chunks are removed (not just
  when new chunks appear) - Fix contract doc: get() for removed-document detection uses
  include=["metadatas"], not include=[] - Fix data-model doc: remove non-existent contentHash from
  metadata schema, correct embeddingType values and documentId descriptions

* fix: address CodeRabbit review round 2 — fallback reset, BoK removal

- Reset all partial dedup state on change detection failure: clear pre-loaded embeddings,
  chunks_skipped, changed_document_ids so EmbedStep correctly re-embeds all chunks on fallback -
  Include removed_document_ids in BoK skip condition so the overview regenerates when documents
  disappear from the corpus

* fix: address CodeRabbit review round 3 — skip cleanup on write failure

- Skip OrphanCleanupStep when StoreStep had batch failures to prevent deleting old chunks when
  replacements weren't stored - Update spec to document summary cleanup and StoreStep error guard

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Early ACK with async processing for ingest pipelines
  ([#78](https://github.com/alkem-io/virtual-contributor/pull/78),
  [`b5a9fa6`](https://github.com/alkem-io/virtual-contributor/commit/b5a9fa63de2e68a75d2007aecfd74e7ce22fbac4))

* feat: early ACK with async processing for ingest pipelines (#1824)

Decouple RabbitMQ message acknowledgment from pipeline completion to eliminate consumer_timeout
  redelivery loops that caused 30 redeliveries and 4,299 wasted LLM API calls in production.

- Ingest events (IngestWebsite, IngestBodyOfKnowledge) are ACKed immediately after schema
  validation, then processed as fire-and-forget asyncio tasks - Engine queries retain late-ACK with
  retry/reject logic - Outer asyncio.wait_for() timeout wraps all plugin.handle() calls
  (configurable via PIPELINE_TIMEOUT, default 3600s) - Graceful shutdown awaits in-flight pipeline
  tasks (30s grace period) - New consume_with_message() adapter method exposes raw message for
  application-layer ACK control - New republish_with_headers() adapter method for retry republishing

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: rewrite SDD artifacts to follow SpecKit templates for story alkemio#1824

Move artifacts from specs/008 (conflicting number) to specs/015 with all 7 required SDD artifacts in
  proper template format: spec.md, plan.md, tasks.md, research.md, data-model.md, quickstart.md, and
  checklists/requirements.md. All tasks marked complete.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Formalize destructive step handling in pipeline engine
  ([#76](https://github.com/alkem-io/virtual-contributor/pull/76),
  [`74d9c49`](https://github.com/alkem-io/virtual-contributor/commit/74d9c491f912dc0d0813cb9e3f807b458e910755))

* feat: formalize destructive step handling in pipeline engine (#37)

Add engine-level safety gate that automatically skips steps declaring `destructive=True` when prior
  pipeline errors exist, replacing the fragile string-matching guard in OrphanCleanupStep.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: rewrite SDD artifacts to follow SpecKit templates for story #37

* fix: address CodeRabbit findings on spec artifacts for story #37

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Implement concurrency in DocumentSummaryStep
  ([#74](https://github.com/alkem-io/virtual-contributor/pull/74),
  [`682a597`](https://github.com/alkem-io/virtual-contributor/commit/682a5973c1801b529710cd23a708cfaa6f376f43))

* feat: implement semaphore-bounded concurrency in DocumentSummaryStep

Wire the existing but unused concurrency parameter to actual asyncio.gather with Semaphore, using a
  collect-and-apply pattern that avoids race conditions on shared PipelineContext state. 5-10x
  speedup for document summarization in typical ingest workloads.

Closes alkemio#1823

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: add missing SDD artifacts for story alkemio#1823

The story worker produced only code and tests but no SDD artifacts. This adds all 7 required
  artifacts to specs/014-concurrent-document-summary/: spec.md, plan.md, tasks.md, research.md,
  data-model.md, quickstart.md, and checklists/requirements.md.

* fix: address CodeRabbit findings on research.md for story alkemio#1823

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Incremental embedding -- embed documents as they finish summarization
  ([#73](https://github.com/alkem-io/virtual-contributor/pull/73),
  [`61aafeb`](https://github.com/alkem-io/virtual-contributor/commit/61aafebf11a17a9a0f02d44bcbc09c974fbde824))

* feat: incremental embedding — embed documents as they finish summarization (#1826)

Extends DocumentSummaryStep with optional embeddings_port to embed each document's chunks
  immediately after its summary is produced, overlapping LLM-bound summarization with GPU-bound
  embedding and reducing pipeline wall-clock time. EmbedStep remains as a safety net for BoK summary
  and below-threshold documents.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: rewrite SDD artifacts to follow SpecKit templates for story alkemio#1826

* fix: overlap embedding with summarization via background tasks and validate embed_batch_size

Addresses CodeRabbit PR #73 review findings:

1. (MAJOR) Embedding now runs as background asyncio tasks instead of being awaited inline in the
  per-document loop. This allows summarization of the next document to proceed while the previous
  document's chunks are being embedded. A semaphore bounded by self._concurrency limits parallel
  embedding tasks. All tasks are collected and awaited after the loop.

2. (Minor) Added validation that embed_batch_size >= 1 in the constructor, matching the existing
  chunk_threshold validation pattern.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Initialize project scaffold with microkernel architecture and PRD
  ([`eafb04d`](https://github.com/alkem-io/virtual-contributor/commit/eafb04dd3c33be53cb386b9a088cd6dff1235abb))

Set up the unified virtual-contributor repository structure: - core/ with ports, adapters, domain,
  and events directories - plugins/ for expert, generic, guidance, openai_assistant, ingest_space,
  ingest_website - Comprehensive PRD documenting analysis of all 8 source repos, architectural
  patterns (Microkernel, Hexagonal/Ports-and-Adapters, Content-Based Router), migration strategy,
  and consolidated environment variable reference.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Instruction-aware embedding queries (spec 028)
  ([#89](https://github.com/alkem-io/virtual-contributor/pull/89),
  [`9388805`](https://github.com/alkem-io/virtual-contributor/commit/9388805968dde93b6b576a2f3fce6136b4d9dc99))

* feat: instruction-aware embedding queries with SDD spec 028

Split EmbeddingsPort into embed (indexing) and embed_query (retrieval) with instruction prefix
  support for Qwen3-Embedding models.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* docs: fix markdown lint in spec artifacts

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Multi-provider LLM support (Mistral, OpenAI, Anthropic)
  ([#4](https://github.com/alkem-io/virtual-contributor/pull/4),
  [`617702b`](https://github.com/alkem-io/virtual-contributor/commit/617702b47aeb246c5a3b6548418f7da47966abf8))

* feat: multi-provider LLM support with unified adapter and provider factory

Replace per-provider LLM adapters (MistralAdapter, OpenAILLMAdapter) with a unified
  LangChainLLMAdapter and a provider factory that resolves the correct LangChain model class from
  configuration. Providers (Mistral, OpenAI, Anthropic) are selected via LLM_PROVIDER env var — no
  code changes needed to switch.

- Add LLMProvider enum and provider config fields with validation - Create unified
  LangChainLLMAdapter wrapping any BaseChatModel - Create provider factory with default models per
  provider (FR-013) - Add backward compatibility for MISTRAL_API_KEY/MISTRAL_SMALL_MODEL_NAME -
  Support local/self-hosted models via LLM_BASE_URL - Add per-plugin provider override via
  {PLUGIN_NAME}_LLM_* env vars - Harden structured output JSON parsing in guidance plugin - Pass
  pre-computed embeddings through ChromaDB adapter - Add 60 new tests (config validation, adapter,
  factory, structured output) - Add ADR 0005 and full SDD spec artifacts

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: address CodeRabbit review feedback on PR #4

- Move .env.example inline comments to separate lines to avoid dotenv-linter warnings from spaces
  before # in values - Move not-found check inside _delete() so delete_collection doesn't burn all
  retries with backoff on non-existent collections - Update provider-config.md per-plugin example to
  use the actual {PLUGIN_NAME}_LLM_* prefixed env vars - Remove unused asyncio import from
  test_langchain_llm.py (F401) - Remove unused pytest import from test_guidance_structured_output.py
  (F401)

* fix: remove stray merge conflict marker in chromadb.py

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Rag evaluation framework with RAGAS metrics
  ([#33](https://github.com/alkem-io/virtual-contributor/pull/33),
  [`b85f10b`](https://github.com/alkem-io/virtual-contributor/commit/b85f10b4c8fbabb640709ed22e565a2ae59e9e3c))

* feat: RAG evaluation framework with RAGAS metrics and golden test set

Adds a CLI-based evaluation framework (evaluation/) that measures RAG pipeline quality using four
  RAGAS metrics (faithfulness, answer relevancy, context precision, context recall) against a
  curated golden test set. The framework uses the pipeline's own LLM as judge via LangChain wrapper
  to preserve data sovereignty, supports synthetic test generation from indexed content, persists
  run results as JSON, and produces before/after comparison reports.

CLI commands: run, compare, generate, list Tests: 35 new tests (251 total pass)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: resolve ruff lint errors in evaluation framework

Remove unused imports, fix f-string without placeholders, remove unused variable assignments.

* chore: trigger CI re-run for CodeRabbit review

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Space ingest context enrichment & URI tracking
  ([#83](https://github.com/alkem-io/virtual-contributor/pull/83),
  [`f0d365e`](https://github.com/alkem-io/virtual-contributor/commit/f0d365ee65f6bfa7a5462a0cfe62457bb7a93f65))

* chore: enhances space ingestion with cleaning and deduplication

Injects a GraphQL client for the ingest-space plugin, configured via settings or environment
  variables, to enable API queries.

Rewrites the space tree reader for robust content extraction from the Alkemio hierarchy. Integrates
  HTML stripping and content normalization for cleaner, consistent documents. Implements content
  deduplication to prevent redundant documents and improves overall data quality. Updates the
  GraphQL query and processing logic for various content types like spaces, callouts, posts,
  whiteboards, and links.

* feat: enrich ingested contributions with callout context and propagate entity URIs

Prepends parent callout title and truncated description to each contribution (post, whiteboard,
  link) so chunked content retains hierarchical context for better RAG retrieval. Propagates entity
  URLs from the Alkemio GraphQL API through DocumentMetadata and StoreStep to the vector store,
  enabling clickable source links.

Includes SDD spec 022 artifacts and 12 new unit tests.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: address CodeRabbit review — GraphQL client guard and empty-URI test

Require admin_password in GraphQL client construction check. Add test for empty-string URI omission
  in StoreStep.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Unified microkernel virtual contributor engine
  ([#1](https://github.com/alkem-io/virtual-contributor/pull/1),
  [`9b16fbc`](https://github.com/alkem-io/virtual-contributor/commit/9b16fbc1731c08cc47761837c53d891a96a632ac))

* feat: implement unified microkernel virtual contributor engine

Consolidate 7 standalone repositories into a single Python 3.12 codebase using microkernel +
  hexagonal architecture. Single Docker image serves all 6 plugin types (expert, generic, guidance,
  openai-assistant, ingest-website, ingest-space) selected at runtime via PLUGIN_TYPE env var.

- Core: event models, port protocols, IoC container, plugin registry, content-based router, health
  server, structured logging - Domain: PromptGraph, ingest pipeline, summarization graph - Adapters:
  Mistral, OpenAI, ChromaDB, RabbitMQ, Scaleway, OpenAI embeddings - Plugins: 6 handlers preserving
  backward-compatible wire format - Tests: 125 tests, 87% coverage (excluding infrastructure
  adapters) - CI/CD: Dockerfile, docker-compose, 3 GitHub Actions workflows - Docs: 4 ADRs, README,
  quickstart

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

* fix: add ruff to dev dependencies and fix all lint errors

- Add ruff ^0.11.4 to pyproject.toml dev dependencies - Remove unused imports across core, plugins,
  and tests (36 auto-fixes) - Remove unused variable assignment in rabbitmq adapter

* fix: add pyrightconfig.json and fix ChatMistral import

- Add pyrightconfig.json with basic type checking mode, demoting pydantic populate_by_name false
  positives to warnings - Fix ChatMistral → ChatMistralAI (correct langchain-mistralai class name)

* fix: use self-hosted M4 runner for CI tests and lint

Match alkem-io/server CI convention: self-hosted macOS ARM64 M4 runner for lint and test jobs,
  ubuntu-latest for build/deploy.

* fix: use system Python venv instead of setup-python on self-hosted runner

actions/setup-python@v5 fails on the self-hosted M4 runner due to /Users/runner permission error.
  Use the pre-installed python3 to create a venv instead.

* fix: use Homebrew Python 3.12 on self-hosted M4 runner

System Python on the runner is 3.9.6 but project requires ^3.12. Use /opt/homebrew/bin/python3.12 to
  create the venv.

* fix: set AGENT_TOOLSDIRECTORY for setup-python on self-hosted runner

The runner runs as /Users/m1 but setup-python defaults to /Users/runner for its tool cache. Set
  AGENT_TOOLSDIRECTORY to a writable location.

* fix: also set RUNNER_TOOL_CACHE for setup-python compatibility

setup-python uses RUNNER_TOOL_CACHE internally, not AGENT_TOOLSDIRECTORY.

* fix: use ubuntu-latest for CI (self-hosted runner lacks Python 3.12)

The self-hosted M4 runner has Python 3.9.6 and setup-python cannot install Python 3.12 due to tool
  cache path permissions. Since our CI tests are pure unit tests with mocked dependencies (no
  databases or infrastructure), ubuntu-latest is appropriate. The self-hosted runner is reserved for
  the server repo which requires database bootstrapping.

* chore: remove M4 self-hosted runner reference from constitution

The specific runner hardware is an implementation detail. This repo uses ubuntu-latest for CI since
  tests are pure unit tests with no infrastructure dependencies.

* fix: address CodeRabbit review findings

- pre-commit: use ruff-check hook ID (ruff is legacy) - CLAUDE.md: fix broken template markers in
  commands section - rabbitmq: bind queues to DIRECT exchange, let exceptions escape
  message.process() so failed messages are requeued/dead-lettered - main.py: include original event
  in error response envelope - ingest-space: accept graphql_client via constructor, delete
  collection only after successful fetch (prevents data loss) - crawler: add SSRF protection
  blocking private/reserved/loopback addresses before fetching

* fix: router priority and retry edge case (CodeRabbit round 2)

- router: check plugin_type before eventType to prevent cross-plugin misclassification (ingest-space
  messages with eventType field) - chromadb: handle max_retries=0 edge case with explicit
  RuntimeError instead of raising None

* fix: chromadb delete retry + space_reader null safety (CodeRabbit round 2)

- chromadb: use _retry for delete_collection, catch ValueError specifically for non-existent
  collections instead of bare Exception - space_reader: use `or {}` / `or []` pattern after .get()
  to handle GraphQL explicit null values (key exists with None value)

* fix: remove unused sys import, skip optional deps in container resolution

- main.py: remove unused sys import - container: resolve_for_plugin now skips parameters with
  default values when no adapter is registered, instead of raising ContainerError. Fixes
  ingest-space plugin whose graphql_client has a default of None.

---------

Co-authored-by: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Refactoring

- Rename ScalewayEmbeddingsAdapter to OpenAICompatibleEmbeddingsAdapter
  ([`dca8c9d`](https://github.com/alkem-io/virtual-contributor/commit/dca8c9d9334d75dd2b6d26b4a094f0123c6c32cd))

The adapter is a generic OpenAI-compatible HTTP embeddings client, not Scaleway-specific. Rename
  class, file, and references to reflect the actual API standard it implements. Remove
  vendor-specific default model name from the adapter constructor (now required).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
