# CHANGELOG


## v0.3.0 (2026-08-14)

### Chores

- Merge main (v0.2.0 release commits) back into develop before promotion
  ([`c2638cc`](https://github.com/alkem-io/virtual-contributor/commit/c2638cc58287c1c694a5ec64a5eff8e9281d5efd))


## v0.2.0 (2026-08-04)

### Features

- Distroless non-root runtime image (workspace#026)
  ([`471474a`](https://github.com/alkem-io/virtual-contributor/commit/471474a1be78437654425ab9a4c88266ac70fc04))


## v0.1.3 (2026-05-11)


## v0.1.2 (2026-04-27)


## v0.1.1 (2026-04-27)


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

- **ci**: Add v prefix to Docker Hub semver tags
  ([`62d404b`](https://github.com/alkem-io/virtual-contributor/commit/62d404b1c5e822e90576b136593131f580d4cfdb))

Align with Alkemio convention: alkemio/[repo]:v[version].

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

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

- **faithfulness**: Close review findings on precision and log egress
  ([`5549139`](https://github.com/alkem-io/virtual-contributor/commit/55491398476b62180e89f89c982dc2511a868aaf))

Adversarial panel found the check was flagging the exact behaviour it exists to protect, and leaking
  member content by two channels.

Precision — 13/13 spurious flags, now 0/13. Every apologetic decline ("I'm sorry, I don't have that
  information", "I'm not sure about that one") was condemned as a fabrication. A flag that fires on
  a correct refusal is the worst error this feature can make. Two causes: the phrase list did not
  cover apologetic or colloquial forms, and the regex could not match a contracted negation at all —
  \bn't\b leaves no word boundary before the "n" inside "don't", the same defect already recorded
  for "I don't know". Contractions are now matched as whole words. Verified in both directions: all
  three real fabrications still flag.

Graph path — every answer was flagged. combined_knowledge_docs is absent from state on the non-RAG
  path, so its default "" read as empty context. Validation now runs only when the key is present.

Log egress, two channels. verdict.detail is free text a substituted validator could build from the
  member's answer, and exc_info=True prints the traceback with the answer in a local frame. Logs
  reach central logging, readable by log access rather than by space membership. Reasons now pass a
  KNOWN_REASONS allow-list (isinstance-guarded, since `in` calls __eq__ and a non-str can spoof
  membership); exceptions log only the type.

No-egress guard was bypassed two ways in review, both now closed. The deny-list could only name
  clients someone had thought of — langchain_openai, this repo's own route to Mistral, was not on it
  and never would have been; it is an allow-list now. And the port-implementation sweep read only
  core/, so a validator in plugins/ importing httpx outright was invisible; it sweeps the repo. Both
  bypasses replayed and confirmed failing.

Also: hedges are found in a closing caveat (two fixed windows, still O(1) — 10 MB stays at 3.4 ms),
  the sentinel compares case-folded, and the port docstring records that a blocking implementation
  blocks every message this worker serves, not just its own.

676 passed, coverage 89%, ruff clean, pyright 0 errors.

Refs alkem-io/virtual-contributor#27

- **faithfulness**: Key graph validation off retrieval, not the caller's schema
  ([`25bcf66`](https://github.com/alkem-io/virtual-contributor/commit/25bcf66949ef4626a68da59023526e42b36d6e6e))

The graph definition arrives on the event, so its state schema belongs to the caller. LangGraph
  drops any key the schema does not declare — proved directly: a retrieve node returning
  combined_knowledge_docs against a schema that omits it yields final_state keys
  ['current_question'].

Reading the key back from final_state therefore collapsed two different situations into one absence:
  "this graph never retrieved" and "this graph retrieved, found nothing, and the schema dropped the
  evidence". The first must not be validated; the second is the entire case this feature exists to
  catch. A space configuring a RAG prompt graph without listing that key turned the check off and
  nothing said so.

Validation now keys off a closure the retrieve node writes to. That code knows which situation it is
  in; the final state cannot.

The existing graph tests could not have caught this: they mock PromptGraph wholesale, so retrieve
  never runs. They now drive a real compiled graph and stub only the answering node (the mock LLM is
  not an LCEL Runnable, and retrieve is the node under test). Confirmed by reverting the fix — the
  new test fails, the other 14 still pass.

679 passed, coverage 90%, ruff clean, pyright 0 errors.

Refs alkem-io/virtual-contributor#27

- **faithfulness**: Narrow hedge suppression, validate the member's answer
  ([`c4893dd`](https://github.com/alkem-io/virtual-contributor/commit/c4893dd901d53052dbea5ef812de03723f2a4923))

A second review pass found that fixing the 13/13 spurious flags had over-corrected: suppression grew
  wide enough to swallow the signal. Both directions are now pinned by the corpora that exposed
  them.

The structural rule matched any negation within 60 chars of a common noun, so ordinary assertions
  about limits were read as declines and never flagged — 8 of 9 measured. "The platform does not
  support SAML; only OIDC records are kept" is a claim, not a refusal. Negated assertions are how a
  model states a constraint, and Alkemio's own vocabulary (knowledge, context, data, records) is
  exactly the noun set, so this failed on a large and ordinary class of answers. The rule now
  requires a first-person subject: the SPEAKER must be the one lacking the information.

Bare apologies were admitted as substrings, so "I'm sorry to hear that. The space was founded in
  1997 by Dr. Amelia Hartwell." was suppressed. An apology is the most common opener there is; as a
  substring it hands the model a prefix that switches the check off. Only phrases that themselves
  state the lack remain. Measured after both fixes: 0/13 declines flagged, 0/11 assertions
  suppressed.

Guidance validated the raw LLM output, but retrieve_prompt asks for a JSON envelope whose own
  "sources" key is an information-noun — so whether a fabrication was detected depended on the
  model's serialisation format rather than on what it said, and answer_chars logged the envelope's
  length (82) instead of the answer's (53), corrupting the one measurement this feature exists to
  collect. It now validates the string the member receives.

Also: the contract file named six test files that never existed, so seven clauses exited 4 or 5 —
  and "no tests ran" is indistinguishable from green in a `-q | tail` pipeline. All 13 clauses now
  resolve and pass. C-3's grep matched the docstring explaining why overlap scoring was rejected; it
  points at the AST check instead. Port exported per T003.

693 passed, coverage 90%, ruff clean, pyright 0 errors.

Refs alkem-io/virtual-contributor#27

- **ingest**: Panel review — reconcile the fingerprint and metadata rules (workspace#043)
  ([`22785cf`](https://github.com/alkem-io/virtual-contributor/commit/22785cfa7ed1d7c8ffed203f97fbed62e83f3bda))

Five findings from the correctness/quality/spec panel. Two were defects the previous commit
  introduced while fixing the security review.

Position is now all-or-nothing, governed by one predicate shared by the fingerprint and the metadata
  renderer. Sparing positionless content from the fingerprint while still writing it a depth
  recreated, for website corpora, exactly the silent drop this feature exists to fix: a legacy entry
  keeps its old id, the write is skipped, and the depth never lands. Reproduced against a real
  legacy-shaped entry, then reproved: website content stores no position fields at all, so skipping
  the rewrite discards nothing, while space content is rewritten and gains its position including a
  depth of 0.

The null-id tolerance was half-applied — the position calls were softened but the document_id
  subscripts beside them were not, so a malformed callout still took down the whole ingestion, now
  with a None reaching the fingerprint join. A node with no stable identity is skipped outright: it
  could never be change-detected or swept, and its healthy siblings still ingest.

depth is no longer droppable. A positioned entry missing it would be invisible to a depth filter,
  and it would go missing exactly when something upstream is already wrong, so an unusable value
  coerces to the root tier loudly. bool is excluded deliberately — it subclasses int, and True would
  fail a depth filter.

Also pinned: the failed-campaign-run path, where the destructive gate leaves both fingerprint
  regimes in place until a clean run converges them, and the root-name preference, which no test
  previously distinguished.

Refs alkem-io/virtual-contributor#17

- **ingest**: Protect legacy summaries, and let the new label actually land (workspace#044)
  ([`5f80672`](https://github.com/alkem-io/virtual-contributor/commit/5f80672712af8e828aebbf0c493798dd275c4cc6))

Three findings from review, all reproduced against the real steps before and after. The first was a
  defect this feature introduced.

Treating an unlabelled entry as content is right for passages — it is what keeps the pre-label
  corpus sweepable — but a legacy summary carries no label either, and the ids collected there feed
  the removed-document set. So the first run after deploy deleted every legacy per-document summary
  and the corpus overview outright. Verified absent on develop, so it was ours. An entry that is
  recognisably derived by its id is now excluded regardless of label, and both summarisation steps
  share the id conventions so they cannot drift from the check that reads them. The sweep of
  genuinely removed content is unaffected.

The label now participates in the fingerprint. Without it a description already in the corpus kept
  its old label forever: the text is unchanged, so the id is unchanged, so the write is skipped and
  the new label is computed and then discarded — the same silent drop this pipeline invites every
  time. Appending the label unconditionally was the obvious fix and was wrong: it re-fingerprints
  every passage in the corpus for a label that did not change. Only a non-chunk label is appended,
  so exactly the passages whose label changes are rewritten. Measured: post, knowledge, callout,
  link and whiteboard fingerprints are byte-identical to develop; only descriptions move.

That also stops two passages of identical text with different labels from colliding on one storage
  id and overwriting each other.

Refs alkem-io/virtual-contributor#18

- **ingest**: Scope the derived-id fallback, surface bad overlap (workspace#044)
  ([`0c89214`](https://github.com/alkem-io/virtual-contributor/commit/0c892143279065454f3311acfb182c981a557e2c))

Three findings from the review panel. The first was a regression the previous commit introduced
  while fixing a different one.

Website document ids are page URLs, so excluding every id ending in "-summary" meant a page like
  /2024-annual-summary was never swept when it disappeared upstream — the same
  survive-your-own-deletion failure this area exists to prevent, reintroduced on another path.
  Verified against develop, which sweeps it correctly. The id fallback now applies only where the
  label is actually missing, which is the only case it was introduced for.

That fallback rested on a claim I did not check: that entries predating the label carry no label.
  They do carry one — every revision of the pipeline has written it, and both plugins deleted the
  collection outright before content-hash dedup landed, so no unlabelled corpus can exist. The rule
  stays as defensive totality, which is the safe direction for an unknown entry, but the historical
  story is gone from the docstrings and the contract. It was load-bearing for a conclusion it did
  not support.

An overlap at or above the chunk size is an operator error the splitter used to reject loudly.
  Clamping it silently traded a fail-fast for a permanent cost multiplier, so it now clamps to zero
  — neutral, rather than an invented fraction — and warns.

Refs alkem-io/virtual-contributor#18

- **ingest**: Security review — spare positionless corpora, sanitise names (workspace#043)
  ([`1134bf3`](https://github.com/alkem-io/virtual-contributor/commit/1134bf3248c39d0f99ab8c4e5c0cbf4f2fe78db2))

Four findings from the SOC 2 / ISO 27001 review, all fixed.

Website collections were being re-fingerprinted for nothing. The position segments were appended
  unconditionally, so every website chunk got a new storage id and a full re-embed while gaining no
  position at all — the exact opposite of the guarantee FR-013 was written to make. Content with no
  tree position now keeps the fingerprint it had before this feature; verified byte-identical
  against develop. The shipped regression test only checked metadata keys, so all 601 tests stayed
  green while the invariant was violated; there is now a test that pins the storage fingerprint
  itself.

Display names are user-controlled and are stored under a new key that later work will filter on and
  may render. The `or raw` fallback meant a name that is nothing but markup was stored verbatim, and
  entity decoding could turn &lt;script&gt; back into live markup. A pure-markup name is now treated
  as unknown, which the omit-on-unknown design already handles, and stripping runs past the decode.

A malformed node no longer aborts the whole ingestion: position lookups use tolerant access, so a
  missing id costs only its own position.

The render helper now enforces the whole scalar contract it documents rather than only the None
  half, and logs what it drops — otherwise a future non-scalar field would silently take up to 50
  chunks out of the corpus.

Refs alkem-io/virtual-contributor#17

- **ingest**: Sizing config now reaches website ingestion; correct two env vars
  ([`dfe848e`](https://github.com/alkem-io/virtual-contributor/commit/dfe848e7c98451179c6dc813a7f828548432c0e3))

CodeRabbit triage on PR #110. All three findings were real, and all three are the same shape: a knob
  that looks configured and is not.

SUMMARY_LENGTH, CHUNK_SIZE and CHUNK_OVERLAP never reached website ingestion. main.py injects by
  signature, and IngestWebsitePlugin did not declare them — so its ChunkStep was hardcoded to 2000
  and both summary steps used constructor defaults whatever an operator set. IngestSpacePlugin
  declared all three, so the two ingest paths silently disagreed. A knob honoured by one path and
  ignored by the other is worse than one honoured by neither: it looks configured. Both plugins now
  accept the same set, asserted directly so they cannot drift again.

This is precisely what this PR's own story is about — tuning chunk size, overlap and summary length
  — so shipping it with half the tuning inert would have been the worst possible outcome.

.env.example advertised BATCH_SIZE. Runtime reads INGEST_BATCH_SIZE, so that line was ignored and
  ingestion used the code default of 5 while the file said 20.

plugins/ingest_space/README.md listed ALKEMIO_SERVER as required. No code reads it; main.py reads
  API_ENDPOINT_PRIVATE_GRAPHQL. An operator following that table leaves the GraphQL client
  unconfigured and every space ingest fails.

Both doc errors predate this PR (BATCH_SIZE dates to the initial microkernel commit) but live in
  files it touches, and both misconfigure the thing this PR is tuning.

Verified the new tests fail against the old signature.

592 passed, ruff clean, pyright 0 errors.

Refs alkem-io/virtual-contributor#10

- **ingest-space**: Review round 1 — startup probe, scoped sizing log, website summary assertion
  ([`1199c29`](https://github.com/alkem-io/virtual-contributor/commit/1199c2921848a9fbedd8fa00841212d7fe10c33a))

CQ-1: _load_config read PLUGIN_TYPE via a throwaway BaseConfig(), so a legal ingest-space
  CHUNK_OVERLAP between 2000 and 2499 aborted startup citing a chunk_size the operator never set.
  Read the env var directly and construct exactly one config class. CQ-3: sizing is logged only for
  plugins whose constructor consumes it — reporting CHUNK_SIZE for ingest-website (which ignores it)
  recreated the false confidence the detector exists to prevent. CQ-2: website summary length
  follows the shared SUMMARY_LENGTH by design (story #12's dilution rationale is path-independent);
  the regression test now asserts both halves — chunking pinned at 2000/400, summary at 2500 — so
  the choice is enforced, not incidental. Spec A-08 and FR-012 amended to match.

workspace#042-vc-chunk-tuning

- **ingest-space**: Route alkemio-knowledge-base BoKs to lookup.knowledgeBase() (spec 033)
  ([#100](https://github.com/alkem-io/virtual-contributor/pull/100),
  [`6b9beb9`](https://github.com/alkem-io/virtual-contributor/commit/6b9beb964a6638edb91d7dde73c48d07f1ecfc57))

* fix(ingest-space): route alkemio-knowledge-base BoKs to lookup.knowledgeBase()

The ingest_space plugin always issued lookup.space() regardless of bodyOfKnowledgeType. ~29% of VCs
  (69 of 238 on acceptance) are backed by an alkemio-knowledge-base, which lives in a different
  table and 404s on lookup.space(), causing the ingest pipeline to abort and leaving an empty
  collection that produces hallucinated answers downstream.

Add read_knowledge_base_tree() that issues lookup.knowledgeBase() and a read_body_of_knowledge()
  dispatcher that selects the reader based on event.type. Unknown types fall back to the space
  reader (dominant case).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

* docs: SDD spec 033 — ingest space knowledge-base routing

Retrospec for the routing fix that branches IngestBodyOfKnowledge events to lookup.knowledgeBase()
  vs lookup.space() based on event.type.

Records: spec, plan, research decisions, data model, GraphQL contract, quickstart, task breakdown
  (all complete), and quality checklist.

* docs(033): apply /speckit.analyze remediations (A5, A6)

A5: Reframe spec.md SC-002 as a VC-side observable — counts result envelopes with the specific
  failure signature on the VC's own RabbitMQ result stream — so the criterion is verifiable without
  server-log access.

A6: Drop the hardcoded "528 tests" count from tasks.md T020 so the task description doesn't drift as
  the codebase grows.

* fix(ingest-space): generalize log messages and tighten dispatch tests

Address CodeRabbit review on PR #100:

- Rename "Space" -> "BoK" in the zero-document cleanup info log and the catch-all exception log so
  that logs reflect the post-routing semantics (both alkemio-space and alkemio-knowledge-base events
  now flow through this plugin). Aids incident triage. - Extend the two
  TestIngestSpacePluginDispatchesOnType cases to assert, in addition to leaf-reader routing, that no
  LLM/embeddings work was performed on the empty-document cleanup branch (llm.calls,
  embeddings.calls, embeddings.query_calls all empty) and that no collection deletion was issued
  (store.deleted empty). This satisfies the repo testing convention of asserting LLM and
  knowledge-store interactions in plugin tests.

---------

Co-authored-by: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

- **ingest-space**: Security round 1 — bound sizing config, honour .env plugin-type binding
  ([`82aa112`](https://github.com/alkem-io/virtual-contributor/commit/82aa1125a995f968500d77149239db381c82de4f))

SEC-1: validation admitted CHUNK_OVERLAP just under CHUNK_SIZE, which amplifies embedding volume
  ~238x at runtime under a 3h ingest budget — exactly the failure class the validation exists to
  prevent. Overlap is now capped at half the chunk size and CHUNK_SIZE at MAX_CHUNK_SIZE (100k),
  both at startup. SEC-2 (defect introduced by the CQ-1 fix): resolving PLUGIN_TYPE via a raw
  os.environ read dropped pydantic's .env binding, so a documented local-dev path silently loaded
  BaseConfig and ingested at 2000/400. A minimal _PluginTypeProbe shares BaseConfig's env_file
  binding while staying field-minimal, so it cannot re-introduce the startup abort the CQ-1 fix
  removed. Both pinned by regression tests.

workspace#042-vc-chunk-tuning

- **ingest-space**: Security round 2 low — pin probe binding to BaseConfig, document sizing bounds
  ([`d5f21b1`](https://github.com/alkem-io/virtual-contributor/commit/d5f21b1e907a93ee3a1b12d788c32b083fb96394))

sec-vc-5: _PluginTypeProbe now derives model_config from BaseConfig instead of duplicating it as a
  literal, so a future change to the env binding cannot silently reopen SEC-2 (wrong sizing, no
  error); parity asserted by test. sec-vc-6: permitted ranges documented in .env.example. sec-vc-4
  (shared-BaseConfig validation coupling) recorded as accepted design — the wave-1 PRs delete these
  keys and ADR 0009 forbids re-pinning them; failure mode is a loud startup abort, not silent
  corruption.

workspace#042-vc-chunk-tuning

- **ingest-website**: Include identification fields in result envelope (spec 032)
  ([#99](https://github.com/alkem-io/virtual-contributor/pull/99),
  [`e607059`](https://github.com/alkem-io/virtual-contributor/commit/e607059e9b5dbeda7282b1a6490acbff39be197b))

* fix(ingest-website): include identification fields in result envelope

The result-message wire format published by ingest plugins is `{"response": {...IngestWebsiteResult
  fields...}}`. The alkemio-server `IngestWebsiteResultHandler` reads identification fields from
  `event.response` to call `updatePersonaBoKLastUpdated()` against the right persona.

Pre-fix `IngestWebsiteResult` only carried `timestamp`, `result` and `error` — no way for the server
  to correlate a successful website ingest back to a persona, which crashed the handler with `Cannot
  read properties of undefined (reading 'personaId')` on every incoming result on dev.

Adding the identification fields and propagating them from the incoming `IngestWebsite` request
  through every code path that constructs `IngestWebsiteResult` (cleanup-only branch, success
  branch, exception branch). `bodyOfKnowledgeId` defaults to an empty string because website-typed
  bodies of knowledge are URL-identified, not UUID-keyed.

Pairs with the matching server-side fix on alkem-io/server which makes both ingest result handlers
  read from `event.response.*` to match what the wire actually carries.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

* docs: SDD spec 032 — ingest website result correlation fields

Retrospec for the additive change that adds bodyOfKnowledgeId, type, purpose, and personaId to the
  IngestWebsiteResult envelope so the alkemio-server can correlate every result back to its
  originating persona.

Records: spec, plan, research decisions, data model, wire contract, quickstart, task breakdown (all
  complete), and quality checklist.

* docs(032): apply /speckit.analyze remediations (A4, A2)

A4: Clarify in contracts/ingest-website-result.md that consumer-side implementation lives in the
  alkemio-server repo and is out of scope for this contract; producer-side guarantees only.

A2: Drop placeholder tasks T021/T022 ("covered-by" entries with no independent work); fold their
  intent into T013 (schema edit) and T020 (test assertion). Note left in tasks.md explaining the
  consolidation.

* docs(032): apply CodeRabbit feedback on PR #99

- data-model.md: add `text` language tag to the request-to-response field-mapping fence to satisfy
  markdownlint MD040. - tasks.md: drop stale `T021` reference from Phase 3 dependency text so it
  stays consistent with the later note that T021 was folded into T013. -
  tests/plugins/test_ingest_website.py: assert `result.body_of_knowledge_id == ""` on both the
  normal-ingest and cleanup-only paths to lock in the full result envelope contract documented in
  data-model.md.

---------

Co-authored-by: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

- **prompts**: Bound the citable document set; pin ReDoS structurally
  ([`08067ac`](https://github.com/alkem-io/virtual-contributor/commit/08067ac5b00bbfa2f22c559087b02378e7db84aa))

CodeRabbit round 2 on PR #109. Two findings addressed, two declined.

SEC-1 (major, valid): passage bodies are rendered verbatim by contract, so a retrieved passage
  containing header-like text puts that text in the prompt. The citation rule said "cite only
  document numbers that appear in the supplied context" — which that forged text satisfies. A
  poisoned passage could therefore license a citation to a document with no sources[] entry behind
  it. Metadata sanitization (SEC-2, previous round) does not reach this: it guards labels, not
  bodies.

Fixed by bounding the citable set by count rather than by appearance. citation_scope_instruction(n)
  states the exact supplied range, rendered into both answering prompts from the count of blocks
  actually built: len(docs) for expert simple-RAG, len(deduped) for guidance. With no documents it
  forbids citing any number. CITATION_INSTRUCTIONS now also defines a label as only the bracketed
  header opening a block, and marks bracketed text inside a body as quoted content that must never
  be cited.

This strengthens the citation instruction rather than weakening it, which matters downstream: PR
  #117 cannot build citation verification (vc#27 Option D) until generation asks for citations that
  can be validated against a known set. A bounded range is what makes that check possible.

CQ-3 (minor, valid): both README document-block fences get a text language.

5 new assertions fail against the pre-fix wording; verified by reverting the instruction text and
  the two prompt placeholders and watching each fail, then restoring.

Declined, both with executed evidence in the PR thread:

- Retry/temperature (major): LangChainLLMAdapter already implements MAX_RETRIES=3 / BASE_DELAY=1.0
  behind LLMPort. Measured through the helper: 3 provider attempts in 3.02s. Adding the requested
  second loop gives 9 attempts in 12.07s on a dead provider. The graph half is correct-as-designed:
  ADR 0013 scopes answering_temperature to the two repository-owned answering calls, and graph node
  prompts are platform-owned (prompt_graph.py is untouched by this PR).

- Timing assertion (minor): the finding is right that wall-clock is load-sensitive, but deleting the
  assertion outright drops the coverage. Measured: the assertion cannot discriminate what it claims
  to guard — restoring the vulnerable pre-SEC-1 regex still passes at ~16.9ms against a 50ms
  threshold, while a loaded runner reaches 31ms. So it is simultaneously too loose to catch the bug
  and tight enough to flake. Replaced with two deterministic guards: a structural check that no
  module pattern contains the unbounded [^?]* span, and a sys.settrace step-count linearity check.
  Verified the structural guard fails when the vulnerable regex is reintroduced — which the timing
  assertion did not.

ruff clean, pyright 0 errors, pytest 629 -> 638 passed.

workspace#041-vc-generation-prompts

- **prompts**: Review round 1 remediation — ReDoS closed, labels sanitized, temperature contract
  coupled
  ([`fb73032`](https://github.com/alkem-io/virtual-contributor/commit/fb73032ff1aa2bb6f27102fece9a81d2bad669bd))

SEC-1 (high): interrogative detection rewritten as a token-list check (no backtracking regex) +
  classification bounded to text[:2000] — pathological 32KB input drops from 4.6s of event-loop
  blocking to <1ms; performance test pins it. SEC-2: document-label metadata sanitized (whitespace
  collapsed, [ ] · stripped, per-value truncation) so poisoned titles cannot forge [Document N]
  headers or blow the context window; rendered label bytes now count against MAX_CONTEXT_CHARS (ADR
  0013 consequence updated); forged-header + oversize tests added. SEC-3+SEC-4/CQ-1+CQ-2 (coupled,
  one change): LLMPort.invoke + LangChainLLMAdapter.invoke gain explicit temperature param — adapter
  introspects the underlying model and binds per call (never mutates shared state); main.py injects
  answering_temperature + chain_of_thought_enabled alongside the other tuning params and logs
  effective values at startup; real-adapter kwarg test + wiring test. SEC-5/D: decline instruction
  driven by structural has_context, not sentinel matching — passage containing the sentinel text no
  longer triggers the decline path. CQ-3: classifier documented English-only + fullwidth ？ counted;

non-English truth-table row pinned. CQ-4: empty-context test asserts the rendered context slot.
  CQ-6: dead dropped=0 (039 residue) deleted. CQ-7: exc_info reverted to develop's form (belongs to
  PR #107).

CQ-8: README ADR index + .env.example ANSWERING_* entries.

workspace#041-vc-generation-prompts

- **rerank**: Coderabbit triage — import-scan hole, optional-port resolution
  ([`c62f85e`](https://github.com/alkem-io/virtual-contributor/commit/c62f85e8e2612dd21a37f47f7f4c18d29e788230))

Four of six CodeRabbit findings on PR #115 were real. Two were not, and are declined with executed
  evidence in the PR thread.

Addressed:

1. tests/core/domain/test_rerank_no_egress.py — the transitive privacy scan could be stepped around.
  _imported_names retained only node.module, so "from core.domain import helper" resolved to
  core/domain/__init__.py and stopped there; helper.py itself was never scanned. Relative imports
  lost their level entirely and vanished from the graph. A helper that imports httpx could therefore
  join the re-ranking path with the guard still green — worse than no guard, since the passing test
  is what stops anyone looking. ImportFrom now yields both the package and each member, and relative
  imports resolve against the importing file's own package.

2. core/container.py — resolve_for_plugin looked the annotation up verbatim, so "Port | None" never
  matched a registered Port. An optional port could only be supplied by bypassing the container,
  which is exactly why the re-ranker was constructed by hand in main.py. Optional unions now unwrap
  to the underlying port; genuine multi-type unions are left alone. The unresolvable-union error
  path also died with AttributeError, because types.UnionType has no __name__ — it now names the
  annotation.

3. main.py — the re-ranker is registered on the container when enabled and arrives through normal
  injection. Only its scalar settings are still injected, and only when the port is actually
  present, so a disabled deployment carries no re-ranking numbers it never uses.

4. tests/plugins/test_expert_rerank.py — test_disabled_preserves_store_order asserted only the
  requested candidate count, which the test above it already covers; it passed unchanged while
  sources were reordered. It now asserts the source order itself, including the term-matching
  passage staying third.

Also adds the disabled-path funnel coverage CodeRabbit correctly noted was missing, and corrects the
  rerank_lexical_weight docstring: the accepted range is 0.0-1.0, and the constraint it was groping
  at is that a weight in (0.0, 0.5] is a validated setting that provably cannot promote a
  worst-on-vector passage.

656 -> 664 tests passing. ruff clean, pyright 0 errors (46 warnings, unchanged from baseline).

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>

- **rerank**: Panel findings — truncation starved the context window
  ([`27fe640`](https://github.com/alkem-io/virtual-contributor/commit/27fe64013bba5040401c823af2b5e5e9dc09ce94))

The high finding was mine and real. Expert truncated to RERANK_TOP_K inside _apply_rerank, BEFORE
  the relevance threshold ran. Re-ranking legitimately lifts term-matching passages that sit below
  the threshold, so those filled the whole top-K and were then all discarded -- reproduced end to
  end: a pool where the disabled path returns 5 grounded sources returned ZERO with re-ranking on,
  leaving the LLM to answer ungrounded with no error anywhere. Truncation now happens after the
  threshold, where guidance already did it. Over 400 randomised pools the enabled path went from
  'fewer sources in 6, more in 0' to 'fewer in 0, more in 330' -- the stage was subtracting from
  answers, not adding.

Also from the panel: - lexical scores could reach ~2.19 for a short exact match (BM25 saturation
  with length normalisation). Invisible today because the caller rescales, but the docstring
  promised [0,1] and a second port implementation would have believed it. Clamped. - the 0.6 default
  was justified as clearing the tie boundary 'with margin'. The real boundary is w > 1/(2 - L0); 0.6
  only clears it when the incumbent's own lexical score is under 1/3. Docstring now states the
  condition instead of overstating the value. - mismatched vector_scores/documents raised an opaque
  IndexError one way and was silently truncated by zip the other. Now an explicit ValueError. - a
  None document raised AttributeError and turned a working answer into an error response. Now scores
  zero. - an oversized query blocked the event loop for ~973ms (measured) against a 1.5-CPU pod.
  Query/term/document caps bring that to 1.8ms.

Two test-durability fixes, both verified by attacking them: - the no-egress import scan covered
  three hardcoded files. A helper module POSTing query+documents, imported from rerank.py, passed
  all nine tests. The scan now walks the import graph transitively and catches exactly that. - the
  no-new-dependency guard ran git diff with check=False, so under CI's shallow checkout it passed
  without comparing anything. It now skips loudly when the base ref is unresolvable, plus a
  base-ref-independent manifest check that cannot pass vacuously.

656 passed, coverage 88.88%.

- **retrieval**: Bound the length of a single search term (workspace#045)
  ([`049d174`](https://github.com/alkem-io/virtual-contributor/commit/049d174e79026b7abfb854a41f8a9066db22cc68))

Capping the number of terms does not bound what reaches the store: one unbroken 100,000-character
  word is a single term and a 100,000-character pattern. Nothing a person types as a name or
  identifier comes close to the limit, so anything longer is not a search term — and an over-long
  word no longer suppresses the real terms beside it.

Refs alkem-io/virtual-contributor#22

- **retrieval**: Coderabbit round three — redaction, muted arms, dense-only order
  ([`88b6f30`](https://github.com/alkem-io/virtual-contributor/commit/88b6f3007ad55be1877a082a8e494795a89f328f))

Three behavioural findings on PR #114, each measured before and after, each with a regression test
  verified to fail without its fix.

1. Redact the lexical retry log (chromadb.py). query_lexical sends the member's own words to the
  store in where_document, and Chroma's validate_where_document formats that whole filter into its
  ValueError. The retry warning therefore wrote member search terms to the log, going around the
  redaction the fusion layer already applies when the lexical arm fails. _retry gains an opt-in
  redact_errors mode that logs the exception type only; the exception itself is raised unchanged,
  and every other operation keeps its detailed message.

Proven: with the fix reverted, the retry log contained the probe term 'myrarediseasename'.

2. A zero weight now mutes an arm instead of scoring it zero. Config permits one weight of zero and
  the config tests describe it as muting an arm, but both arms were still queried and fused. RRF
  keeps any document any arm returned, so the muted arm's ids surfaced whenever fewer than n_results
  documents had a positive score. A muted dense arm could also still fail the whole request. Muted
  now means not queried, not fused, and not able to fail the request; a muted lexical arm also skips
  the capability check and term extraction.

Measured before: lexical muted -> fused ids ['dense-1', 'lex-1', 'lex-2']; dense muted -> ['lex-1',
  'lex-2', 'dense-1'] and a dense error still raised. After: ['dense-1'] and ['lex-1', 'lex-2'], no
  exception.

3. Restore global score ordering when hybrid retrieval is off. The new rank-first sort ran on every
  request, including the dense-only path. Because the list is truncated to n_results immediately
  afterwards, this did not merely reorder sources — it changed which ones survived. With three
  collections of unequal quality, the strong collection's second and third hits (scores 0.90 and
  0.85) were displaced by a weak collection's hits (0.50 and 0.45). Rank ordering now applies only
  when the feature is enabled, so disabling it is a true rollback.

Also extends the shared MockKnowledgeStorePort in the hybrid test fakes, so both arms' call tracking
  comes from one place and the fakes satisfy KnowledgeStorePort. The capability-absent fake inside
  the muted-arm test stays a plain class deliberately — it exists to lack query_lexical.

Gates: ruff clean, pyright 0 errors, pytest 641 -> 656 passed.

- **retrieval**: Review round 1 remediation — scope-creep revert + test fidelity
  ([`a27b5d5`](https://github.com/alkem-io/virtual-contributor/commit/a27b5d574eb73ac02218986ab07dd6cc3b6cc246))

S-1: revert the unspecified expert prompt change ('No relevant context found.' sentinel) — expert
  keeps its pre-feature empty-Knowledge-block behavior; the test now asserts FR-010's actual
  requirement (filtered query ran, no exception, summaries absent from the prompt) instead of
  enforcing the sentinel. Spec Edge Cases/FR-010 corrected at the source. CQ-1: guidance
  degraded-path test gains positive discriminators (query calls + filter identity) so a store-side
  filter rejection can no longer pass green; guidance query-failure log now carries exc_info (also
  security SEC-2 note). S-2/CQ-3: truth-table test now pins MockKnowledgeStorePort._matches_where
  itself — single shared evaluator, R-4 mitigation genuine. CQ-2: adapter forwarding test uses the
  real FACTUAL_WHERE (single-element $and is invalid on a live server). CQ-4: mock evaluates where
  against unseeded-collection canned results (G1-shaped metadata) instead of bypassing filter
  evaluation. CQ-5: ChromaDB _retry surfaces deterministic ValueError validation failures
  immediately instead of burning backoff retries.

workspace#040-vc-retrieval-filter

- **retrieval**: Round two of review findings (workspace#045)
  ([`7274194`](https://github.com/alkem-io/virtual-contributor/commit/727419497b30f9a9d88d1c17d12590b61ec921dc))

A length rule alone was discarding the names this arm exists to match. AI, S3, v2, k8s and GDPR were
  all shorter than the minimum and silently dropped, so the lexical arm was blind to a large class
  of the identifiers people actually ask about. A short word is kept when the member wrote it like a
  name — not all-lowercase, or mixing letters and digits — while ordinary filler still yields
  nothing.

NaN and infinite fusion weights passed validation. NaN compares false against everything, so it
  slipped past the bounds and would have made result ordering arbitrary at runtime rather than
  failing at startup where it belongs.

A store without a lexical query raised outside the degradation handler, turning an absent capability
  into a failed request. Retrieval is still correct without the arm, so it now falls back and says
  so.

The failure log interpolated the store's exception, which can echo a member's own query terms back
  into the log. It records the exception type instead.

Refs alkem-io/virtual-contributor#22

- **retrieval**: Round-2 closure — genuine degraded-path discriminator, decode-error retry carve-out
  ([`3da99ce`](https://github.com/alkem-io/virtual-contributor/commit/3da99ceee36284161dfedacc73650ca4d81c908a))

CQ-1 (final): the guidance degraded-path test now asserts the absence of the 'Failed to query
  collection' warning — the one observable that actually differs between 'correctly filtered
  everything out' and 'every query threw and was swallowed' (the earlier query_calls discriminators
  held on both paths since the mock records calls before evaluating). corr-vc-r2-1/qual-vc-r2-2:
  _retry fast-fail narrowed — JSONDecodeError (ValueError subclass; transient proxy-502 bodies)
  keeps the full retry ladder; contract pinned by a direct _retry test (1 attempt vs 3).

workspace#040-vc-retrieval-filter

- **retrieval**: Three review findings, all of them mine (workspace#045)
  ([`df19490`](https://github.com/alkem-io/virtual-contributor/commit/df1949099e51c765e773bfde9733c53b045b49b3))

The feature's own published conformance script failed against the code that claimed to implement it.
  Fusion preferred whichever arm happened to supply a number, so a lexical arm reporting scores of
  its own — which the design explicitly anticipates as a future replacement — would inject a
  fabricated *semantic* distance into the relevance threshold and into what an answer cites. That is
  the confusion widening the type was meant to prevent. Distance now comes from the dense arm and
  nowhere else, while text and metadata are still recovered from whichever arm actually fetched
  them. The tests missed it because they only ever built a lexical arm pre-set to None, so they
  exercised the one case the bug could not reach.

Guidance called the lexical arm three times per question, paid its latency, and then discarded its
  only distinctive contribution. It merged the three collections by score, which sinks every
  literally-matched passage below every scored one; the truncation then cut it. The merge is now by
  rank within each collection — the fused order, which is the only ordering that means anything
  across arms — and within a rank an unscored passage comes first, because it already earned its
  place against the semantic hits inside its own collection. At default settings the term-bearing
  passage is now cited; before, it was not.

The rollback path had stopped being a rollback. Two different things look like "no distance": a
  passage matched literally, which the semantic threshold cannot judge, and a distance simply
  missing from a short list, which is a malformed result that scored zero and was dropped.
  Conflating them changed behaviour with the feature switched off. They are now distinguished, and
  parity with the prior code is asserted for both shapes.

Refs alkem-io/virtual-contributor#22

- **rewrite**: Answer model sees the resolved question; bounds now configurable
  ([`6e6251f`](https://github.com/alkem-io/virtual-contributor/commit/6e6251f890c9b8d7ad80b4e267e0574f79a5b566))

CodeRabbit triage on PR #118. Two of the five majors were real; three were already satisfied.

The answer prompt got the RAW message. Retrieval used the resolved question, but
  combined_expert_prompt still received event.message — and that prompt carries no conversation
  history, so an anaphor arrived with nothing to resolve against. The model was asked "and the other
  one?" over chunks retrieved for "What are the L1 spaces in the Alkemio platform?". Proved by
  capturing both prompts before and after. When no resolution happened, question IS event.message,
  so the no-history path is unchanged.

history_length was still unwired. It exists only on ExpertConfig and OpenAIAssistantConfig, so it
  can never serve guidance or generic — the bounds now live on BaseConfig and every rewriting plugin
  reads them. Where a plugin does declare history_length, main.py takes the smaller of the two: that
  value is the plugin's own statement about how much history is meaningful, and the rewrite prompt
  should not exceed it. Expert is therefore bounded at 10 turns, not 20.

Declined, with reason: the two findings asking for 3-attempt exponential backoff inside
  rewrite_query. That retry already exists one layer down — core/adapters/langchain_llm.py:64
  implements MAX_RETRIES=3 with BASE_DELAY=1.0 behind LLMPort, which is what rewrite_query calls.
  Adding another loop would make it 9 attempts and up to ~21 s on a dead provider, on the
  pre-retrieval path. The guideline the finding cites is satisfied by the adapter that owns the
  call.

Also declined: the non-finite ratio finding, already fixed in 94a15e2.

760 passed, coverage 90%, ruff clean, pyright 0 errors, 11/11 clauses.

Refs alkem-io/virtual-contributor#24

- **rewrite**: Bound the history embedded in the condense prompt
  ([`7f011ea`](https://github.com/alkem-io/virtual-contributor/commit/7f011ea2baddc54feb79c9a5b5a3c48f79f8b8ea))

The condense prompt embeds the whole conversation and nothing bounded it. history_length has existed
  in core/config.py since before this feature and is read by no code at all — the config knob for
  exactly this was written and never wired up.

The member supplies the history, so the size of that third-party prompt was theirs to choose.
  Measured through the generic plugin:

turns before after reduction 2 1,380 1,380 0.0% 50 25,860 10,560 59.2% 500 255,360 10,560 95.9% 5000
  2,550,360 10,560 99.6%

2.5 MB per request to a metered API, on a path that runs before the answer call. Present on develop
  identically; the gate this feature adds is simply the first place it was cheap to fix.

Keeps the trailing 20 turns, matching the existing ExpertConfig default — the tail is what a
  follow-up refers to. A malformed history yields an empty list rather than raising, because it must
  not be the reason a request fails, and a non-positive bound opts out.

695 passed, coverage 90%, ruff clean, pyright 0 errors, 11/11 clauses.

Refs alkem-io/virtual-contributor#24

- **rewrite**: Close review findings — gate boundary, graph seam, untested policy
  ([`fe1f3d6`](https://github.com/alkem-io/virtual-contributor/commit/fe1f3d6414adb7e33ec8281153a8b3b51809aafe))

Adversarial review found the gate boundary was not safe as claimed, and that the expert graph path
  could pay for a rewrite and discard it.

Gate boundary — a regression against develop. The real classifier routes "ok", "okay", "alright",
  "will do", "later", "got it" to CONVERSATIONAL, so they skipped. But after "Shall I list the
  subspaces and their leads?", "ok" means do it — and the vector store was searched for the literal
  string "ok" instead of the offer the member just accepted. The classifier excludes bare
  "yes"/"no"/"sure" for exactly this reason and its docstring says so; it simply does not extend
  that to these. The policy now holds them back. Gratitude and closings still skip, which is the
  case the saving was measured on.

My own tests could not have caught this: the stand-in policy asserted "ok" as a CORRECT skip. Tests
  now drive the decision through a classifier stub that mirrors the real routing.

Expert graph path — the state seam alone was not enough. The graph definition arrives on the event,
  so its schema belongs to the caller, and LangGraph drops any key the schema does not declare. A
  graph that simply did not list rephrased_question paid for the condense call and silently
  discarded the result — worse than not rewriting, on both axes this feature optimises.
  retrieve_node now closes over the resolved question; the state seeding remains for graphs that
  route it themselves, and a graph node writing that key still wins.

main.py had no tests at all. Three mutations of it survived the whole suite: inverting the fail-open
  handler (every turn during a classifier outage would skip its rewrite), removing the try/except (a
  classifier exception fails the request), and dropping the enable-flag check (gating turns on for
  everyone). All three now fail.

Also bounded the graph path's history. Bounding only the rewrite prompt was incoherent — the same
  member-supplied history builds a conversation string and a messages list that go straight to the
  graph's LLM nodes: 2,550,025 chars and 5,001 entries, now 10,225 and 21.

And US1-AS4 had no test: an acknowledgement carrying a question ("ok so what now", "thanks for the
  space overview, what about subspaces?") must still rewrite. Correct already, now pinned — it is
  the load-bearing boundary of the whole gate.

Contract clause C-11 greps its own guard file, so it reported failure on a compliant implementation.
  Narrowed to the gate and plugins.

734 passed, coverage 90%, ruff clean, pyright 0 errors, 11/11 clauses.

Refs alkem-io/virtual-contributor#24

- **rewrite**: Close security findings — config bypass, prompt volume, policy purity
  ([`94a15e2`](https://github.com/alkem-io/virtual-contributor/commit/94a15e241dd1038c1f4f6a7707314df5b3e9b428))

Security review returned conditional with two mediums. Both are closed.

The ratio validator rejected <= 1.0 but admitted inf, nan, 1e308 and 1e400, each of which silently
  disables the length bound this feature exists to enforce. nan is the worst: every comparison
  against it is False, so the check is not merely large but structurally unreachable, while startup
  logs a plausible-looking value. Measured — all four passed validation and then accepted a 100
  000-char rewrite. Now requires a finite value in (1.0, 100.0]; an upper bound matters as much as
  finiteness, since 1e308 is finite.

The turn bound left the character volume to the member. The platform caps a room message at 32 784
  chars, so 20 turns is still ~656 000 chars — about 164 000 tokens — re-sent to a metered
  third-party API on every turn of a thread. Added a character budget alongside the turn count,
  mirroring the max_context_chars pattern already used for retrieved chunks: oldest turns evicted
  first, and at least one turn always kept, because dropping every turn would silently defeat the
  resolution the prompt exists to perform. 656 000 -> ~33 000 chars.

The no-egress guard proved query_rewrite.py pure but never reached the policy, which is a duck-typed
  object injected from main.py. RewritePolicy is runtime_checkable, so a future policy doing I/O
  would satisfy it, pass every guard test, and block the event loop inside should_rewrite — the
  exact call this gate removes. Now asserted at the seam, including a timing check that catches an
  I/O policy importing nothing the test can name.

The acknowledgement hold-back stripped only trailing !.? so "ok," and "ok…" slipped through to be
  skipped. Normalises on the Unicode punctuation category now — a list that is trivially
  side-stepped by punctuation is not a list.

Reviewer also flagged the graph precedence change: an empty rephrased_question now falls through to
  the resolution. Kept and documented — a schema field declared but never written reads as "" too,
  and that is the common case; the two are indistinguishable through state.get, and there was no
  rewriting on develop for a graph to suppress.

What the review confirmed holds: retrieval scope cannot be crossed by a crafted rewrite (collection
  derives from the event envelope before the rewrite runs), no log record carries message, history
  or rewrite content, and both fail-open directions are safe and not weaponisable.

757 passed, coverage 90%, ruff clean, pyright 0 errors, 11/11 clauses.

Refs alkem-io/virtual-contributor#24

- **routing**: A disabled feature must not be able to stop the pod
  ([`d4882b4`](https://github.com/alkem-io/virtual-contributor/commit/d4882b47d9bdd75bfb2f27c7637aa42317bf06d9))

CodeRabbit triage on PR #116. The finding was right and the consequence is a boot failure on an
  existing, valid deployment.

ROUTING_COMPLEX_CONTEXT_CHARS was compared against MAX_CONTEXT_CHARS, which is not a routing
  setting. Routing ships disabled by default, but that relational check ran unconditionally — so a
  deployment running MAX_CONTEXT_CHARS=2000, perfectly valid on develop, was rejected at startup by
  this feature's own 40000 default, for a value no routing code would ever read. Verified: the
  config now boots with routing off and is still correctly rejected with routing on.

Scoping the check exposed a second hole, which is why this is not a one-line change. An existing
  test asserted that an absurd routing_complex_context_chars of 1e12 is rejected — and it was, but
  only as a side effect of the relational check. With that scoped, an extra zero in an env var would
  have been accepted. Added an absolute ceiling that applies whether or not routing is enabled: a
  misconfiguration is a misconfiguration regardless of which code reads it.

Verified the new test fails when the fix is reverted.

799 passed, ruff clean, pyright 0 errors.

Refs alkem-io/virtual-contributor#29

- **routing**: Bound classifier input before scanning
  ([`9472487`](https://github.com/alkem-io/virtual-contributor/commit/947248730c1ab4b3bace691e791ab0f2085dba7f))

Classification is synchronous and runs on the event loop, so an oversized message blocks every other
  message in the process while being scanned. Measured before the fix: 437ms for a 10MB query, 153ms
  for a 25MB single token, against a pod limited to roughly 1.5 CPU. After: 2.9ms and 0.03ms.

The cost was message.split() in the word-count gate, not the regexes -- I probed those directly for
  catastrophic backtracking (nested alternation with a repeated group is the classic ReDoS shape)
  and they are linear even unguarded: 4KB of adversarial separators matches in 0.3ms.

Truncating cannot cause the one harmful misclassification. A message long enough to be truncated is
  by construction far longer than the six-word small-talk limit, so the cap can only move a message
  away from the retrieval-skipping route, never toward it. Asserted.

- **routing**: Correctness panel — two high findings, both mine
  ([`18e22f4`](https://github.com/alkem-io/virtual-contributor/commit/18e22f4e246ef5d7b32b8d933e0b4d891a669c41))

The routing table was built from the DEPRECATED GLOBALS, not from the settings the plugins are
  actually constructed with. Production sets EXPERT_MIN_SCORE and GUIDANCE_MIN_SCORE to 0.1 and
  never sets RETRIEVAL_SCORE_THRESHOLD, so every profile carried the 0.3 default: the moment routing
  was enabled, every routed query would have filtered at triple the threshold nobody configured.
  Measured by the reviewer on realistic scores: routing off keeps 5 chunks, routing on keeps 2 on
  simple, moderate AND complex -- the COMPLEX route asking for 10 and delivering fewer than develop
  does today, the headline behaviour inverted. The builder now takes the plugin's effective knobs;
  simple is clamped never to exceed them and complex never to fall below them. My own test had
  asserted the bug, so it asserted the wrong thing; it now proves parity.

The expert graph classified the raw turn but retrieved on the rephrased one. "Shall I list the
  templates in this space?" / "yes" becomes a real standalone question by the time retrieve_node
  runs -- and the closure had already captured a skip-retrieval decision made on the word "yes", so
  it threw away the real query it was holding and answered ungrounded. Exactly the one mistake the
  safety asymmetry says is impossible. The closure now classifies the query it is about to run.
  Guidance was already safe: it condenses first, then classifies.

Also removed bare affirmatives from the small-talk list: yes, yep, yeah, no, nope, maybe, sure,
  please, pls, right. Unlike "thanks", none of those asserts that nothing should be looked up --
  after an offer, "yes" is the shortest way to say do it. They now fall through to retrieval, which
  is today's behaviour, so excluding them costs nothing.

795 passed, coverage 88.91%.

- **routing**: Security panel — the port seam was trusted but unconstrained
  ([`472933c`](https://github.com/alkem-io/virtual-contributor/commit/472933c5511eb20231da91e5e05a56d2109466a0))

All five findings share one root cause: QueryRouterPort is a Protocol, so nothing enforces what an
  implementation returns or what it does.

The fault barrier wrapped only classify(). A router returning None, a bare string, or an object
  without a route attribute raised straight through -- reproduced on both plugins -- turning every
  query into a retried-then-failed request and breaking the docstring's own promise that
  classification is "never a dependency of answering". Note the str-enum subtlety the reviewer
  found: a plain-string route RESOLVES a real profile from the table before dying on .value. The
  decision is now validated, and profile resolution sits inside the barrier. All four malformed
  shapes now answer.

The no-egress suite pinned the shipped MODULE, not the SEAM. The reviewer built the attack: a
  sibling core/domain/llm_classifier.py POSTing every member question to Mistral satisfies the port,
  is accepted by both plugins, and passed all five tests in 0.01s. The scan now covers every class
  under core/ defining classify(), plus the injection point in main.py. Verified the same attack now
  fails.

The INFO log interpolated the reason string -- free text a substituted classifier could build from
  the member's question, going to stdout and on to central logging. Reproduced with a leaky router
  echoing the query. The reason moved to DEBUG; INFO carries the route only. Asserted.

Config had no upper bounds: a 1TB budget and a 1e9 width both started cleanly, yielding 111 million
  chunks for one query on a 1.5-CPU pod. Also enforced the simple <= RETRIEVAL_N_RESULTS invariant
  that .env.example and the field docstring both stated and nothing checked.

Truncation now happens before strip(), removing the last unbounded pass over attacker-sized input:
  2.9ms -> 0.19ms at 25MB.

Not a finding, worth recording: I probed all three regexes for catastrophic backtracking and they
  are strictly linear -- the repeated-group shape cannot blow up because each iteration must consume
  a literal alternative. The reviewer reached the same result independently. The retrieval-skip gate
  also held against every unicode, zero-width, bidi and homoglyph bypass attempted; it survives on
  the whole-message anchor, not on the ASCII question-mark check.

750 passed, coverage 88.92%.

- **tests**: Restore the tracer instead of clearing it — coverage gate was broken
  ([`2845663`](https://github.com/alkem-io/virtual-contributor/commit/28456635c3d7f4e57d6eff8572f171c81596e65b))

The triage round added a ReDoS linearity test that measures interpreter steps via sys.settrace, and
  cleared the hook with settrace(None) when done. coverage.py measures through that same hook, so
  every module imported after that test read as unexecuted.

The suite still passed, which is what made it hard to see: 639 tests green locally, and the only
  symptom was CI's coverage gate failing with no failing test to point at. One shard reported the
  error and cancelled the other five, so the PR showed 6 failing checks for a single cause.

Measured: 58 percent reported, 91 percent actual — a 33-point phantom drop spread across
  container.py, registry.py, router.py, the crawler and the space reader, none of which this PR
  touches. Develop measures 88, so the drop looked like the PR had shipped a large untested surface.

Confirmed by bisection: fb73032 passed CI, 08067ac failed, and deselecting that single test restored
  91 percent.

Fixed by saving sys.gettrace() and restoring it, so coverage's tracer survives. Added a guard test
  that walks the whole test tree with AST and fails on any settrace(None) or setprofile(None) — this
  failure mode is invisible locally and expensive to diagnose from CI, so it should not be possible
  to reintroduce quietly.

639 passed, coverage 91 percent under the exact CI invocation (--cov-fail-under=80), ruff clean.

Refs alkem-io/virtual-contributor#26

- **tracing**: Coderabbit round-3 triage — end failed LLM spans, stop duplicate replies, harden
  SDK-private reads
  ([`7e5b5fd`](https://github.com/alkem-io/virtual-contributor/commit/7e5b5fd7c5b4327f39b33ff761cd03e1d457d205))

Addressed 5 of 7 CodeRabbit findings on PR #108. Every fix has a regression test that was verified
  to fail without it (revert, watch it fail, restore):

- main.py: a failed message.ack() no longer requeues an answer that already reached the result
  queue. Measured on the real wiring (build_message_handler): with the ACK raising
  ConnectionResetError, publish was called TWICE (the answer, then an "Error:" message) and
  republish_with_headers once, so the broker redelivered and the plugin re-ran. Now the published
  flag suppresses the retry path.

- core/tracing_callbacks.py: on_llm_error ends the span in a finally block. The span is already
  popped from self._spans, so a raising record_failure left it unended and the failed provider call
  never reached the collector.

- core/tracing.py: read TracerProvider._disabled via getattr with a fail-open default.
  configure_tracing() is called unguarded from main(), so a rename of this SDK-private flag in any
  accepted 1.x minor turned an observability detail into a startup crash (AttributeError).

- pyproject.toml: record the SDK/exporter internal-attribute coupling next to the OpenTelemetry
  constraints. Kept the caret range: tightening to ~1.30 would reject the installed and locked
  1.44.0.

- tests/core/test_main_tracing.py: the zero-egress logging assertion was vacuous. _log_config emits
  at INFO, below caplog's default WARNING threshold, so caplog.text was empty and the negative
  assertion passed for the wrong reason. Pin the level and assert the header line is captured first,
  then that no secret appears.

- tests/plugins/test_guidance_tracing.py: bind one event and reuse it, per the pattern of every
  other test in the file.

Declined, with executed evidence recorded on the PR: the reused-span record_failure (the plugin's
  optional_span already records it — the suggestion produced 2 exception events on one span; a new
  test locks it to 1) and the pyrightconfig 3.12 downgrade (CI, Docker and the lockfile all target
  3.13; pyright reports 0 errors under both).

Gates: ruff clean, pyright 0 errors, pytest 619 -> 623 passed.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>

- **tracing**: Drift-gate closure — cancellation is not a failure, crash-path flush restored
  ([`ba5ae15`](https://github.com/alkem-io/virtual-contributor/commit/ba5ae1590b7ed71688b8f110c252c793325e89f9))

corr-vc-drift-1: optional_span catches Exception (not BaseException) so a routine shutdown
  task.cancel() exports status UNSET instead of phantom ERROR/unknown in the SC-006 error rate;
  pinned by a cancellation test. corr-vc-drift-2: main() finally-block runs the same 5s bounded
  daemon-thread flush on the abnormal-exit path — shutdown_on_exit=False had removed the only
  crash-path flush, dropping the spans describing the crash itself.

workspace#039-vc-rag-observability

- **tracing**: Review round 1 remediation — zero-egress hardened, inert global fallback,
  content-gated errors, honest signals
  ([`96c31ee`](https://github.com/alkem-io/virtual-contributor/commit/96c31ee820ec93a0d4050fe190334d815dc00451))

Security (SEC-1..7): exporter now rides an explicit requests.Session (trust_env=False, no proxies,
  pinned headers incl. explicit empty mapping); every env-fallback constructor arg passed explicitly
  (certificate, timeout, compression, BSP bounds); Resource built without ambient merge;
  OTEL_SDK_DISABLED honored truthfully; get_tracer()/current_root_span() fall back to inert no-ops
  (never the ambient global provider) with guards at the engine + guidance call sites;
  record_failure/on_llm_error gated by tracing_capture_content with truncation; endpoint userinfo
  masked in startup logs; callback span map bounded.

Correctness (C-1..C-8): shutdown flush runs off-loop under asyncio.wait_for(5s) with bounded
  exporter retries; token extraction try/finally always ends the span, coerces defensively; guidance
  empty-retrieval computed post-merge (no saturation); typed LLM adapter errors (LLMInvocationError
  subclasses ConnectionError to preserve the caller contract) drive the llm_error taxonomy;
  empty_retrieval mode implemented.

Spec/quality (S-1..S-8, Q-1..Q-13): guidance chunks_passed/ chunks_dropped_budget computed after
  threshold+dedupe+budget; dead code and locals() introspection removed; optional_span() house idiom
  at all sites; imports hoisted; service.version from package metadata; public API typed; real
  main.py wiring tests (both ACK paths, failure modes, concurrency); factory + composition seam
  tests; all missing scenario assertions (US3-AS2/AS3, US5-AS3, US6-AS2, vc.store.*) added; vacuous
  R-3 test made genuine; ADR status + fixture consolidation.

workspace#039-vc-rag-observability

- **tracing**: Round-2 security closure — content-gated store spans, daemonized flush, LLM-timeout
  attribution
  ([`67c6b4b`](https://github.com/alkem-io/virtual-contributor/commit/67c6b4b8c7f20b53c05a326e5390f73338f22c06))

SEC-4 (final): TracedKnowledgeStore spans disable SDK auto-recording
  (record_exception/set_status_on_exception=False) so record_failure() stays the single
  content-gated writer; regression test drives a raising delegate with capture off and asserts
  nothing leaks. sec-vc-r2-1: shutdown flush moved to a daemon thread — bounds process exit (not
  just the event loop) against a blackholed collector. sec-vc-r2-2: main.py exception ladders catch
  LLMInvocationTimeoutError before asyncio.TimeoutError (Python 3.13 alias) so provider timeouts
  attribute as llm_error, not pipeline timeout. sec-vc-r2-3: stray 040 worktree artifact removed;
  worktrees/ gitignored.

workspace#039-vc-rag-observability

- **tracing**: Round-2b closure — ERROR status contract restored, real wiring tests, bounded process
  exit
  ([`9a26a1e`](https://github.com/alkem-io/virtual-contributor/commit/9a26a1e5d0ce41ebc3f9ce517edfdc653b903564))

spec-vc-r2-1: optional_span now records failures itself (content-gated via record_failure +
  classify_failure) so raising retrieval/stage/ingest spans export status ERROR per span-schema —
  SDK auto-recording stays off. S-3b: main.py message handling extracted to module-level
  build_message_handler; tests/core/test_main_tracing.py now drives the REAL wiring on both ACK
  paths (OK root, pipeline timeout, LLM-provider timeout → llm_error, ConnectionError → llm_error,
  concurrent ingest no-cross-parenting). sec-vc-r2-1 (final): TracerProvider(shutdown_on_exit=False)
  — the SDK atexit hook re-ran the blocking flush after main() returned (measured 35s > 30s k8s
  grace); module owns the bounded lifecycle. Guidance _query_collection deduplicated (optional_span
  owns error recording — no double exception events).

workspace#039-vc-rag-observability

### Chores

- Adds Git worktree management
  ([`bdc7fc4`](https://github.com/alkem-io/virtual-contributor/commit/bdc7fc47e1aaa96a063dc5e6a68cf92ee67e2ccd))

Introduces commands and skills for creating and removing Git worktrees. Automates worktree creation
  with new branches and opens a dedicated tmux pane. Implements guided removal, prompting for
  confirmation, closing tmux panes, and offering to delete the local branch.

- Distroless non-root runtime image, locked deps, CI Python 3.13 (workspace#026)
  ([#105](https://github.com/alkem-io/virtual-contributor/pull/105),
  [`04ba7bd`](https://github.com/alkem-io/virtual-contributor/commit/04ba7bd62047c4d735fe4570498922774a5a5802))

* chore(deps): commit poetry.lock and stop ignoring it

Untracks the poetry.lock exclusion so dependencies are pinned and reproducible. Required by the
  distroless image build (workspace#026), which installs production dependencies exclusively from
  the lock and fails the build (`poetry check --lock`) if it drifts from pyproject.toml.

workspace#026-distroless-runtime-images

* feat(docker): rebuild runtime image on distroless Python 3.13 pair

Replaces the python:3.12-slim single-family build with a matched pair: python:3.13.7-slim-trixie
  builder (glibc/Debian, digest-pinned) that installs poetry.lock-only dependencies into a
  relocatable /venv, copied into gcr.io/distroless/python3-debian13:nonroot (digest-pinned) as the
  runtime — no shell, no package manager, UID 65532, CMD ["main.py"] via the distroless python3
  entrypoint. PYTHONPATH exposes /venv site-packages.

The builder's interpreter (recorded to /venv/PYTHON_VERSION) and the distroless runtime's
  interpreter both resolve to Python 3.13 (major.minor match), which is what the compiled-extension
  wheels installed by the builder need to stay ABI-compatible with.

README.md declares readme = "README.md" in pyproject.toml, so it must be copied alongside
  pyproject.toml/poetry.lock for `poetry check --lock` to pass in the builder stage — .dockerignore
  is updated to allow it through its `*.md` exclusion.

Verified: docker build succeeds; image runs as 65532/nonroot with no shell; ~20% smaller than the
  current published v0.1.2 image (195,118,141 -> 155,035,846 bytes).

* feat(docker): add native-import derivation and persisted image-verify regression

docker/native-imports.py mechanically derives, from poetry.lock plus the installed distribution
  metadata, every top-level module shipped by a distribution with at least one compiled
  (non-pure-Python) wheel — no hand-maintained list. Uses RECORD-based file walking rather than
  top_level.txt, since some distributions (e.g. xxhash) declare an internal submodule as if it were
  top-level, which is not actually importable; walking the installed file layout also naturally
  supports implicit namespace packages (e.g. protobuf's `google`).

docker/image-verify.sh is the persisted US3 regression for the vc-runtime-image contract: asserts
  UID 65532 / Cmd == ["main.py"] / no shell, builder-runtime interpreter major.minor match, every
  native module import succeeds inside the built image, and a live six-plugin start matrix (expert,
  generic, guidance, openai-assistant, ingest_website, ingest_space) against RabbitMQ + ChromaDB
  reaching /healthz 200 + /readyz 200 — then emits digest/size evidence lines and asserts a size
  reduction against the baseline image. Includes bounded retry for a rare rabbitmq-image cookie-file
  race on first boot.

Verified locally: all 35 derived native modules import cleanly; all six PLUGIN_TYPE values reach
  healthy+ready against live RabbitMQ/ChromaDB.

* ci: move VC pipelines to Python 3.13 to match the distroless runtime

ci.yml (lint + test matrix) and release.yml now run Python 3.13 instead of 3.12, so CI exercises the
  same interpreter version as the shipped distroless image (gcr.io/distroless/python3-debian13).
  Running gates on 3.12 while the runtime is 3.13 would institutionalize exactly the interpreter/CI
  skew this feature closes.

Verified: poetry env use 3.13 + poetry install + ruff + pyright + pytest (564 passed) all green
  under 3.13 with no source changes required.

* docs: document the distroless image build and verification

Describes the matched Python 3.13 pair, lock-only /venv install, PYTHONPATH relocation, and the
  interpreter-match requirement; documents docker/image-verify.sh as the persisted regression
  command; updates the repo tree diagram and prerequisites (Python 3.13) to match what's actually
  shipped.

* fix(deps): remediate fixable HIGH CVEs in distroless VC image (US5-AS1)

Bumps pypdf 5.9.0 -> 6.14.2 (fixes CVE-2026-59935/-59936, reachable via the ingest_space PDF parser)
  and relocates ragas/click from main to the dev dependency group (evaluation/ is never copied into
  the runtime image, so ragas 0.2.15's CVE-2025-45691 was already unreachable there; moving it out
  of `--only main` drops it and its heavy transitive tree --
  scipy/networkx/scikit-network/pillow/instructor -- from the shipped image entirely, on top of the
  bump to a fixed stable release for local CI use). Fixes a pre-existing flaky asyncio test surfaced
  by the dep bump's shift in pytest-asyncio collection/teardown timing.

Trivy fixable HIGH/CRITICAL: 3 -> 0 (20 -> 17 total HIGH, all remaining are unpatched Debian
  13/trixie OS packages, documented as residual risk in
  docker/verification/US5-AS1-cve-assessment.md). Image size improved 20.48% -> 56.34% reduction vs
  the v0.1.2 baseline as a side effect of dropping ragas's dead-weight transitive deps from the
  runtime image.

Adds the SBOM/CVE/size evidence bundle (docker/verification/) that was missing for this repo
  relative to server's US5-AS1 evidence.

* chore(026): keep only human-readable scan evidence in-repo

Machine JSONs (sbom, trivy before/after) live in the workspace spec's
  forge/verification/evidence/virtual-contributor/ (review advisory spec-vc-1).
  workspace#026-distroless-runtime-images

* fix(026): CodeRabbit round — pin verify tooling images, enforce SC-001 floor, strip pip, correct
  dep evidence

Addresses 4 CodeRabbit findings on PR #105:

- docker/image-verify.sh, docker/verification/US5-AS1-cve-assessment.md: pin rabbitmq, chromadb,
  syft, trivy, and the default baseline image to digests instead of mutable tags, so the persisted
  verification evidence can't silently drift under a re-run. - docker/image-verify.sh: the SC-001
  40% size-reduction floor was only ever WARNed on a missing local baseline (still passing) and
  never actually enforced even when the baseline was present. Now pulls the baseline if absent and
  fails the run below 40%. - Dockerfile: create the builder's /venv with --without-pip. Poetry
  (system site-packages) does all the installing; nothing in the build needs pip inside /venv, and
  the venv was previously carrying a seeded pip into the runtime image, contradicting the README's
  package-manager-free claim. - docker/verification/US5-AS1-cve-assessment.md, sizes.md: correct the
  runtime-dependency evidence — click and docstring-parser are still present in the shipped image
  (main-group transitive deps of langchain-mistralai/langchain-anthropic, unrelated to the
  ragas/click dev-group move) and were wrongly implied to have been removed by that
  reclassification. Both are 0-vulnerability in this scan, so the CVE-remediation conclusion is
  unaffected; only the evidence narrative needed correcting.

Verified: full docker/image-verify.sh regression green (58% size reduction, all 6 plugin types
  healthy, pip absent from runtime), 564/564 pytest, ruff, pyright all green.

Co-Authored-By: Claude <noreply@anthropic.com>

---------

Co-authored-by: Claude <noreply@anthropic.com>

- Link CLAUDE.md to agents-hq ([#103](https://github.com/alkem-io/virtual-contributor/pull/103),
  [`90d5c87`](https://github.com/alkem-io/virtual-contributor/commit/90d5c87d40ef4c5842521e8023a0ef17be1de578))

* chore: link CLAUDE.md to alkemio-workspace

Adds a workspace-context blockquote near the top of CLAUDE.md so Claude sessions opened inside this
  repo know that cross-repo (vertical) feature specs live at alkem-io/alkemio-workspace.

Documentation only. No behaviour change.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

* chore: rebrand workspace link to agents-hq

Repo alkemio-workspace was renamed to agents-hq; update the CLAUDE.md workspace-context link
  accordingly.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

---------

Co-authored-by: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

- Revert version to 0.1.0
  ([`e5c00b7`](https://github.com/alkem-io/virtual-contributor/commit/e5c00b7e01e1c777e8b7997fa05a95093807dbee))

Let semantic-release determine the version from commit history.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Set version to 1.0.0
  ([`2f349ca`](https://github.com/alkem-io/virtual-contributor/commit/2f349ca5f7e4442b4ffce48cf00e1614f8e0c7e2))

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Stage pending changes and fix duplicate disable_thinking block
  ([`2adac30`](https://github.com/alkem-io/virtual-contributor/commit/2adac30c75c276c3497d5fb0b3a804e96647276a))

Remove duplicate disable_thinking block in provider_factory (merge artifact). Include specs/008 PRD.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

- Update GitHub Actions to latest versions
  ([#104](https://github.com/alkem-io/virtual-contributor/pull/104),
  [`f1d5197`](https://github.com/alkem-io/virtual-contributor/commit/f1d5197702e08579040a9c0e5d0f3dcf65eaf981))

* chore: update GitHub Actions to latest versions

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>

* chore: keep python-semantic-release at v9 (v10 needs config migration)

---------

Co-authored-by: Claude Fable 5 <noreply@anthropic.com>

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

- Push develop images to the owning org's GHCR namespace
  ([`115688e`](https://github.com/alkem-io/virtual-contributor/commit/115688e3bd8c497e520098f776e57641805fc987))

Every develop push since 2026-05-29 failed with "denied: permission_denied: The requested
  installation does not exist". The workflow pushed to ghcr.io/alkemio/virtual-contributor — but
  "alkemio" is an unrelated GitHub USER account, and GITHUB_TOKEN can only write packages inside its
  own installation (alkem-io).

IMAGE_NAME is now github.repository (alkem-io/virtual-contributor), matching how the server repo
  publishes to GHCR. The Docker Hub release path keeps the alkemio/ namespace — that one is Docker
  Hub, where it is correct, and it authenticates with its own secrets.

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

- **adr**: Adr 0018 — query rewrite gating, with the expert-path privacy basis
  ([`6895bf1`](https://github.com/alkem-io/virtual-contributor/commit/6895bf10406f0e4af79d774f53da0e5ab6e1e486))

- **adr**: Record the review findings in ADR 0017
  ([`7a1cdbf`](https://github.com/alkem-io/virtual-contributor/commit/7a1cdbf57fabd5119c8d9b87c39015b13e01dda4))

- **faithfulness**: Adr 0017 and plugin READMEs
  ([`93a83d9`](https://github.com/alkem-io/virtual-contributor/commit/93a83d970115f06fb0cdb5c15044efd53db47f6a))

Records why three of the story's four options are unbuildable here (D's prerequisite unmerged, B
  needs an absent GPU, A is not local), why word-overlap scoring was measured and rejected, and the
  two implementation traps found by walking the code: the two plugins represent 'no context'
  differently, and the expert graph path returns no sources by design.

- **faithfulness**: Correct the port extension claim — a judge cannot drop in
  ([`150e12d`](https://github.com/alkem-io/virtual-contributor/commit/150e12d0efd8bfb44068a93244b7038d66ac12d6))

- **ingest**: Correct the defaults claim — depth=0 is a tier, not unknown
  ([`5373de9`](https://github.com/alkem-io/virtual-contributor/commit/5373de9a5ffd2627c35437cc98b14b663d472ff2))

- **retrieval**: Correct the retry carve-out rationale (corr-vc-r3-1)
  ([`33f47a6`](https://github.com/alkem-io/virtual-contributor/commit/33f47a63b87411b7b1fa0b8b41f7fd6bddfd12c0))

Proxy 502s raise a bare Exception in the chromadb client (generic retry branch); the JSONDecodeError
  carve-out's reachable trigger is a truncated/non-JSON body on a 2xx at the orjson response-parse
  step. Comment-only — logic and tests unchanged.

workspace#040-vc-retrieval-filter

- **rewrite**: Record what the length check cannot catch
  ([`728b0eb`](https://github.com/alkem-io/virtual-contributor/commit/728b0ebac1618447340e25703879ef49b8478197))

- **routing**: Adr 0016 and plugin READMEs
  ([`e8f8806`](https://github.com/alkem-io/virtual-contributor/commit/e8f880682f3ab56a4cc404fd50f55a8f9bfdf943))

T019 and T020, both flagged as missing by review.

The ADR records what was decided and why it could not have been decided the way the story proposed:
  the break-even arithmetic that rules out an LLM classifier (measured C = 0.0049ms, so any share of
  cheap traffic wins), that no local LLM exists so both vc#29's Option B and vc#24's 'local LLM'
  criterion describe infrastructure that is not here, that plugins are separate deployments so
  cross-plugin routing is structurally unavailable, that the length heuristic was ablated out after
  contributing zero accuracy, and where vc#24 plugs in.

Plugin READMEs carry the per-plugin specifics: for expert, that both retrieval sites route; for
  guidance, that width applies at both of its application points.

- **tracing**: Adr 0012 (OTel over Langfuse SDK) + README observability section
  ([`6a4873e`](https://github.com/alkem-io/virtual-contributor/commit/6a4873e8a72dbb5383df25feea5d890648e929e7))

workspace#039-vc-rag-observability

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

- **faithfulness**: Detect the one unfaithful answer catchable for free
  ([`2f9667e`](https://github.com/alkem-io/virtual-contributor/commit/2f9667ed510fadf89957409d0af7dbae47d6edf3))

vc#27 recommends a layered approach led by citation verification. That cannot be built on develop:
  no generation prompt asks the model to cite anything, so there is nothing to verify against.
  Citation grounding is PR #109, still open. The local NLI option needs a GPU that does not exist
  and torch in a distroless image with a size floor. And 'all validation runs locally' is already
  false -- generation itself calls Mistral and Scaleway.

What ships is the seam plus the single case that is provable for free: an assertive answer produced
  when retrieval returned NOTHING. There was no evidence, so whatever was said came from elsewhere.

Word-overlap scoring was built, measured, and rejected. There is no threshold separating a
  fabrication from a faithful paraphrase, and it condemns the model for behaving correctly:

faithful paraphrase overlap 0.22-0.56 'I don't have enough information' overlap 0.00 <- correct
  behaviour fabrication overlap 0.00

Any cutoff catching the fabrication also flags the honest refusal. The architect found a further
  disqualifier I had missed: the platform answers in the member's language, so a Dutch answer over
  English context also scores 0.00. That check would have flagged every non-English answer on the
  platform.

So this measures context sufficiency, not content matching. Checking context first is what makes
  paraphrase and translation STRUCTURALLY incapable of being flagged rather than merely unlikely to
  be -- and hedge detection can only ever suppress a flag, so a gap there costs one spurious log
  line, never a wrongly approved answer.

Both empty-context shapes are handled: expert yields '' and guidance yields a sentinel string;
  handling one silently does nothing for half the traffic.

No egress, proved by a transitive import scan over every implementation of the port (not just the
  shipped one -- verified a sibling judge posting to Mistral now fails), a socket-poisoned runtime
  check, and a manifest guard.

- **faithfulness**: Wire the check into all three generation paths
  ([`c36fc2e`](https://github.com/alkem-io/virtual-contributor/commit/c36fc2ec5fe8f389e0c21e15b189d21094e4dae5))

Expert generates in two places and guidance in one. All three validate.

Keyed off the CONTEXT STRING, never Response.sources: the expert graph path returns no sources by
  design, so a sources-keyed check would have flagged 100% of graph answers. Asserted in both
  directions -- the graph path flags on empty knowledge and does NOT flag when knowledge exists,
  despite having no sources either way.

Both empty-context representations are covered: expert yields '' from joining an empty list,
  guidance substitutes a sentinel string. Handling one would have silently done nothing for half the
  traffic.

Observation only. A flagged answer reaches the member byte-identical, and a validator that raises
  never costs anyone their answer -- both asserted. Logs carry counts and reason codes only; a test
  plants a sentence in the answer and asserts it appears in no log record, because these lines go to
  central logging.

Off by default, and disabled means the validator is never constructed -- a structural absence rather
  than a branch inside the check.

649 passed, coverage 88.60%. Gate ran with NO --ignore, confirming the spec correction: develop pins
  datasets 5.0.0 alongside pyarrow 25, and they import together fine.

- **ingest**: Record tree position on every stored entry (workspace#043)
  ([`9803c3f`](https://github.com/alkem-io/virtual-contributor/commit/9803c3f3dbebd4e95cc11eb55b9da762054d445c))

Every chunk, summary and overview now carries where it came from — space, nearest containing
  subspace, framing callout, and tier — so retrieval can be scoped to a part of a space tree.

The position participates in the content fingerprint. Without that, unchanged text keeps its old
  fingerprint, the store skips the write as "unchanged", and the new metadata is computed and then
  silently discarded while ingestion reports success. Display names are deliberately excluded, so a
  rename does not re-embed a whole space.

Unknown position is written by omitting the key: the store rejects None and fails the whole batch it
  belongs to. depth is always written — it is an int whose most common value is 0, so a truthiness
  guard would drop it from exactly the root spaces, root-level callouts and website pages that need
  it.

All three write paths render position through one helper so they cannot diverge; the
  body-of-knowledge overview bypasses StoreStep on its happy path and would otherwise have been
  missed.

Refs alkem-io/virtual-contributor#17

- **ingest**: Size and label each passage by what kind of content it is (workspace#044)
  ([`fb954ac`](https://github.com/alkem-io/virtual-contributor/commit/fb954ac57b08b1bab9f09669e5d7cddf3dc598e2))

A space description is a broad, self-contained statement of what a space is for; cut in half by a
  threshold chosen for long-form posts, neither half answers anything. Descriptions are now kept
  whole and labelled `overview`, posts are split at the detail band, and everything else inherits
  the configured size — the per-kind sizes are overrides, so retuning the global default still takes
  effect where no override exists.

The label is the delicate part. Six pipeline behaviours branch on the embedding type, and each
  spelled "is this content" as == "chunk": content fingerprinting, both halves of change detection,
  storage identity, orphan cleanup, and the corpus-summary input set. Introducing a second content
  label without widening those tests would have left overviews unfingerprinted, invisible to change
  detection, re-embedded on every run, and — the failure that matters — never swept when the space
  they describe is deleted, so retrieval would keep answering for a space that no longer exists.

Both were reproduced against the real steps before the change and reproved after: an overview is now
  fingerprinted, content-addressed, skipped when unchanged, and removed with its source. The
  question is asked once, through a single is_content predicate, so the next label cannot reopen
  this.

An absent embedding type counts as content: entries written before the key existed would otherwise
  become invisible to change detection wholesale.

Refs alkem-io/virtual-contributor#18

- **ingest-space**: Tune chunk sizing to the benchmarked band and close both wiring gaps
  ([`8bb58ae`](https://github.com/alkem-io/virtual-contributor/commit/8bb58aebb2bdf855d3483e3cea20858de3cdc2a2))

Closes the two gaps that made the existing configuration dead code — which is the substance of the
  feature, not the numbers: W1 plugins/ingest_space/plugin.py hardcoded ChunkStep(9000, 500), so
  IngestSpaceConfig was never read; W2 summary_length was never injected in main.py, so the summary
  steps silently used their own signature defaults. New defaults (evidence in research.md):
  chunk_size 9000 → 2500 (~625 tokens, inside the 512-1024 benchmarked optimum), chunk_overlap 500 →
  300 (12% of chunk_size, was 5.6%), summary_length 10000 → 2500 (a summary is embedded as one
  passage, so it belongs in the same band). Adds startup validation for all three (incl. overlap <
  size) and logs the EFFECTIVE values at startup — the permanent detector that makes a silent no-op
  non-repeatable. Website ingestion deliberately untouched at 2000, pinned by regression test.
  Re-ingestion safety (store-before-delete ordering under content -hash change detection) pinned by
  test rather than changed.

Requires corpus re-ingestion to take effect; existing collections keep their current chunking until
  re-ingested.

Closes alkem-io/virtual-contributor#10 Closes alkem-io/virtual-contributor#11 Closes
  alkem-io/virtual-contributor#12 Refs alkem-io/alkemio#1818, workspace#042-vc-chunk-tuning

- **prompts**: Shared grounded context rendering, complexity heuristic, opt-in answering temperature
  ([`cc623fe`](https://github.com/alkem-io/virtual-contributor/commit/cc623feec9630b6b2632c8d085d6b3f3c6e3a222))

core/domain/prompts_shared.py: single-definition labelled document blocks (1-based numbering, label
  fallback chain from existing metadata only — never fabricates a hierarchy path),
  faithfulness/citation instruction constants, step-by-step private-reasoning instruction.
  core/domain/query_complexity.py: pure, inspectable classifier (no model call) for conditional CoT.
  Config: ANSWERING_LLM_TEMPERATURE (opt-in, default unset — existing deployments keep provider
  defaults; llm_temperature untouched) + ANSWERING_CHAIN_OF_THOUGHT_ENABLED kill-switch, both
  validated.

workspace#041-vc-generation-prompts

- **prompts**: Wire grounding into expert/guidance/generic answering paths
  ([`60c5034`](https://github.com/alkem-io/virtual-contributor/commit/60c5034eb47b1415c49ab7da4e0986433124f21c))

Expert + guidance render retrieval context as labelled document blocks and append
  faithfulness/citation instructions; complex questions get the private step-by-step instruction
  (config-gated); answering calls honor the opt-in temperature via LLMPort kwargs. Guidance's
  structured JSON answer contract preserved (instructions additive). Platform-supplied prompt-graph
  node prompts untouched. Envelope sources[] byte-stable — the server never parses answer text
  (verified: room.controller.service).

workspace#041-vc-generation-prompts

- **rerank**: Config, wiring, and the expert plugin stage
  ([`a2844eb`](https://github.com/alkem-io/virtual-contributor/commit/a2844ebbb079551a060ef2f9d1e4c90c92c4aa53))

Four RERANK_* settings, validated at startup so a bad value names itself rather than surfacing later
  as quietly worse answers. Off by default.

The re-ranker is constructed only when enabled, so a deployment that leaves it off keeps its current
  retrieval path exactly -- same n_results requested, no re-ranking code reached. Asserted, along
  with the LLM and store call counts being identical enabled vs disabled: re-ranking is in-process
  and must not add a round trip.

_apply_rerank permutes all four parallel lists together. Distances are carried through unmodified,
  only reordered: the blended score is normalised across the candidate pool, so writing it back
  would corrupt the relevance threshold. The threshold stays on the vector score, and a test pins
  that a re-ranked-first chunk is still excluded when its real distance fails the bar.

- **rerank**: Guidance cross-collection merge + observability
  ([`f7ed58a`](https://github.com/alkem-io/virtual-contributor/commit/f7ed58a0f33aeb62a46d2909248558d021813032))

Guidance is the strongest case for this feature, for a reason vc#23 does not mention. It merges
  candidates from three separately-populated collections by sorting on 1.0-distance, and those
  distances are only loosely comparable: a sparse corpus returns systematically worse distances, so
  its passages lose every cross-collection comparison regardless of how well they answer the
  question. Verified -- with a sparse collection holding the only procedural answer, it is shut out
  of the context window entirely today, and reaches first place once one scorer is applied uniformly
  across the merged pool.

Truncation still happens after dedupe, never before. Cutting to top-K first would let several chunks
  from one page eat the budget and return fewer distinct sources than asked for.

Both plugins log candidate count and elapsed ms, so an operator can see the stage running without
  inferring it from answer quality.

Full suite: 649 passed, 88.88% coverage. No dependency added, no forbidden path touched.

- **rerank**: Lexical re-ranking domain + zero-egress proof
  ([`8668614`](https://github.com/alkem-io/virtual-contributor/commit/86686147374c5b505bd5b298b158cc0b119c49f5))

Adds the re-ranking stage vc#23 asks for: a RerankerPort returning an index permutation, a stdlib
  BM25-style lexical scorer, and a convex blend with the vector score.

Not the neural cross-encoder the story recommends. That option assumes a DGX GPU and 96GB of unified
  memory; there is no GPU in any Alkemio cluster, the pods request 500Mi, and torch would breach the
  distroless image contract. What ships is the stage and the seam, with a scorer measured at ~0.7ms
  for a top-20 rerank -- so the story's <100ms budget is met with two orders of magnitude to spare,
  which the recommended option could not have managed on this hardware.

The default lexical weight is 0.6, not the specified 0.5. Min-max pins the best-vector candidate to
  1.0 and the worst to 0.0, so when the term-matching passage is worst on vector and best on lexical
  the blended scores are exactly w and 1-w. They tie at 0.5 and the stable sort keeps the incumbent
  ahead -- meaning at the specified default the feature provably cannot promote that passage, which
  is the one scenario it exists for. Pinned by a test.

Zero egress is proved three ways rather than asserted: an AST import scan, a runtime check with
  sockets poisoned, and a guard that pyproject/poetry.lock are untouched.

- **retrieval**: Expert + guidance default to legacy-safe factual filter
  ([`f85bfdb`](https://github.com/alkem-io/virtual-contributor/commit/f85bfdb4ed8b05733054cc9459ac59122fbac05c))

Both retrieval plugins pass FACTUAL_WHERE by default; summaries no longer steal retrieval slots in
  standard factual queries. Caller-supplied filters used verbatim, never merged. READMEs + CLAUDE.md
  document the policy.

Closes-ref: alkem-io/virtual-contributor#13 (PR body carries Closes)
  workspace#040-vc-retrieval-filter

- **retrieval**: Hybrid configuration surface and query term extraction (workspace#045)
  ([`6136c23`](https://github.com/alkem-io/virtual-contributor/commit/6136c23ec5492d0b7c7e8bb3ddac881568401a55))

Six settings for a lexical retrieval arm alongside the embedding one, with startup validation in the
  existing validator block so a bad value fails the process rather than quietly degrading every
  answer. Off by default: hybrid changes what all retrieval is grounded in, so it is opted into.

Both weights at zero is rejected outright — every result would score zero and the ordering would be
  arbitrary — while muting one arm stays legal, since that is how the two are compared.

Term extraction pulls the words worth matching literally out of a question: casefolded, stop-words
  dropped, de-duplicated in first-seen order, capped. A question is mostly connective tissue, and
  matching on "the" returns everything, which is the same as returning nothing.

Refs alkem-io/virtual-contributor#22

- **retrieval**: Lexical store arm, rank fusion, and absent-distance handling (workspace#045)
  ([`f4626f4`](https://github.com/alkem-io/virtual-contributor/commit/f4626f44cb827f6abffff678c0cb010433161323))

Adds the second retrieval arm and the function that reconciles it with the first.

The store already supports document-level matching, so the lexical arm runs server-side against the
  same live index as the embedding arm — no second index to build, keep in sync, or invalidate,
  which is what makes this workable in a service where ingestion and querying are separate
  deployments.

Two details there are load-bearing. Matching uses a case-insensitive pattern rather than the obvious
  contains operator, which is case-sensitive — a member asking about "traefik" would otherwise miss
  a passage saying "Traefik", failing silently at precisely the exact-name matching this arm exists
  for. And every term is escaped: a query is text, not a pattern, so left raw a member's own
  punctuation changes what matches and an unbalanced bracket errors their search outright.

Fusion is by reciprocal rank because the two arms measure incomparable things. One reports a vector
  distance; the other reports only that a word is present, with no distance at all. Ranks are the
  one currency both have, so normalising onto a shared scale would mean inventing the missing
  number. A passage found by both arms scores the sum, which is what makes agreement between them
  count.

That absence is now representable: a distance may be None, and the three sites that did arithmetic
  on it branch explicitly. None is not zero — zero would read as a perfect semantic match — and the
  relevance threshold no longer applies to a passage it cannot measure, which would otherwise have
  discarded every literal match before it reached an answer.

Refs alkem-io/virtual-contributor#22

- **retrieval**: Neutral where filtering on KnowledgeStorePort + legacy-safe filter predicates
  ([`0bb05c9`](https://github.com/alkem-io/virtual-contributor/commit/0bb05c97431db6bb3f1e0af67d897528698e02e0))

Port gains optional where (None = unfiltered, mirrors get/delete); ChromaDBAdapter forwards it
  verbatim. FACTUAL_WHERE excludes summaries via $ne/$nin exclusion shape so all three deployed data
  generations (G1 no-key legacy, G2 TS/Py legacy, G3 unified engine) keep matching; legacy TS BoK
  overviews excluded via the $and type-exclusion. SUMMARIES_WHERE ships as the tested
  explicit-summary capability for hierarchical retrieval (vc#19). Truth-table tests pin the mock's
  missing-key semantics. evaluation/tracing.py: minimal pass-through only.

workspace#040-vc-retrieval-filter

- **retrieval**: Run both arms together and fuse them (workspace#045)
  ([`ac6d73c`](https://github.com/alkem-io/virtual-contributor/commit/ac6d73cf8dcea0bfdb80d8c859932747355c8639))

The single place where two rankings become one. Everything downstream — the relevance threshold, the
  context budget, source attribution — sees one ranked set and never learns it was assembled from
  two.

Disabled, this is a passthrough: the embedding query is made exactly as before and the result
  returned untouched, with no lexical call at all. That is what makes the switch a rollback rather
  than a second code path that merely resembles the old one, and it is asserted rather than assumed.

The two arms share one gather, so the lexical arm's latency overlaps the embedding arm's instead of
  being added to it — every answer pays for the slower arm, not the sum. Pinned by a timing test,
  since serialising them would be invisible in any assertion about results.

Failure is deliberately asymmetric. The embedding arm is primary and its failure propagates: an
  answer built without it would be quietly worse than no answer. The lexical arm is an enhancement,
  so losing it degrades retrieval to what it was before this feature rather than failing the
  request.

A question made entirely of common words skips the lexical arm — matching on "the" returns
  everything, which discriminates between nothing.

Refs alkem-io/virtual-contributor#22

- **retrieval**: Wire hybrid retrieval into expert and guidance (workspace#045)
  ([`d5a79aa`](https://github.com/alkem-io/virtual-contributor/commit/d5a79aaef44802cabc3ac2d7256a9e54a40a81df))

Both retrieval plugins now go through the fusion helper, and the container hands them the config so
  the switch is reachable from the environment. Startup logs whether hybrid is on, so which mode a
  replica is running in is answerable from its logs rather than inferred.

The behaviour tests are built around the case the feature exists for: a passage whose wording
  matches exactly but whose embedding similarity is unremarkable, ranked last by the dense arm and
  cut by the relevance threshold. It is now retrieved and cited. Casing does not matter in either
  direction, and a query containing C++, [draft], a|b or ~50% retrieves normally rather than
  erroring — a member's own punctuation must never break their own search.

Parity is asserted rather than assumed: with the flag off, or with no config at all, the same
  sources come back in the same order and the lexical arm is never consulted. That is what makes the
  switch a rollback.

Guidance had two places that turned an absent score into zero — one sorting, one filtering by
  threshold. Both would have silently discarded every literal match before it reached an answer,
  which is the whole feature failing quietly. They now branch on absence explicitly.

Refs alkem-io/virtual-contributor#22

- **rewrite**: Gate, validate, and make survivable the query rewrite
  ([`98282fb`](https://github.com/alkem-io/virtual-contributor/commit/98282fb25ae30fa9e5b4a112ac97596b5e4279ec))

The story asks to add pre-retrieval query transformation, stating the pipeline "passes the raw user
  query directly to embedding similarity search with no transformation". That is false for two of
  three plugins: guidance and generic already send an LLM condense call whenever the event carries
  history. Only expert matched the description.

What was missing is everything around it.

Ungated. The condense fired on ANY history, so a bare "yes" paid a full extra LLM round-trip.
  Measured with a 250 ms stub: "yes", "thanks!", "ok" each cost 2 calls and ~500 ms, identical to a
  real question.

Unvalidated (N-1). Whatever the model returned became the retrieval query verbatim — an empty
  string, a refusal, a chatty preamble. The vector store was then searched for that.

Fatal on failure (N-2). One raised exception from the condense aborted the entire request, though
  the original message was a usable query all along.

Expert now resolves follow-ups at all, via the dormant rephrased_question seam that retrieve_node
  already preferred but nothing ever wrote.

The gate skips CONVERSATIONAL only, NOT SIMPLE. The story recommends skipping simple queries;
  implemented literally that silently breaks anaphoric follow-ups. "show me those", "the name of the
  lead", "and after that?" all classify SIMPLE yet are meaningless without the preceding turn — 9 of
  12 measured. Conversational is the safe boundary because the classifier requires the WHOLE message
  to be small talk, so it cannot carry a question needing resolution. The narrower policy is roughly
  half as fast and correct. A 12-case corpus fails if anyone widens the skip set.

A pure expansion ratio turned out to punish exactly the queries that most need resolving: "who is
  he?" is ten characters, and its correct resolution is 47 — a 4.7x expansion my first cut rejected
  as runaway. Over a 14-turn corpus a ratio of 4.0 rejected 5 legitimate resolutions and 8.0
  rejected 2; an absolute floor of 120 chars rejects none while still catching a model that started
  explaining.

No dependency on the unmerged classifier. This defines its own one-method protocol; main.py alone
  may reach for the real one, inside a guarded import, so the feature builds and runs on develop
  today and starts gating the moment that PR lands. It sits in a ten-PR pile-up on these same files
  (86 conflict hunks measured), so binding to it would have made this hostage to a merge order
  nobody controls.

Also: AC#4 ("all transformation runs on local LLM") is unsatisfiable — there is no local LLM and no
  GPU; every provider is third-party HTTP. The honest claim is that this adds no new external call
  and removes some.

686 passed, coverage 90%, ruff clean, pyright 0 errors, 11/11 contract clauses pass.

Refs alkem-io/virtual-contributor#24

- **routing**: Query classifier and retrieval profiles
  ([`8c7e3ee`](https://github.com/alkem-io/virtual-contributor/commit/8c7e3eeddc9f3387d89542ff09c421526ac39cee))

Adds the seam vc#29 asks for: a QueryRouterPort, a rule-based classifier, and a table mapping each
  route to concrete retrieval settings.

Rules, not an LLM. An LLM classifier costs a network round trip on EVERY query including the simple
  ones it exists to speed up -- at 350ms it needs 39% of all traffic on the cheap path just to break
  even, and that share has never been measured here. Rules cost microseconds, so any share wins.
  Asserted at sub-millisecond, with a socket-poisoned runtime test and a transitive import scan,
  because both plugins already hold an LLMPort and this would be an easy two-line regression.

The classifier is deliberately lopsided. Only one mistake is actually harmful -- routing a real
  question to skip retrieval answers it ungrounded -- so that is the only route with a hard gate:
  the whole message must match an anchored small-talk allow-list, carry no question mark, and be at
  most six words. An earlier substring form routed 'Which subspaces exist here?' to skip retrieval
  because 'hi' appears inside 'which'. Every other misclassification degrades to 'retrieve anyway'.
  Probed with 20 questions engineered to look like small talk: all 16 disguised questions retrieve,
  all 4 genuine acknowledgements skip.

No message-length rule: ablation showed length contributes zero accuracy while misrouting
  verbose-but-trivial lookups. Pinned by test.

Profiles widen budget alongside width. Verified arithmetically that at the deployed CHUNK_SIZE=9000
  the existing 20000-char budget admits only 2 chunks, so widening n_results alone would have been
  completely inert -- a route that looks implemented and changes nothing.

- **routing**: Wire adaptive routing into both retrieval plugins
  ([`e1bced9`](https://github.com/alkem-io/virtual-contributor/commit/e1bced97ea9ba72cb0f1aace7a7cb155fa4dd2a1))

Resolves one profile per query and threads it through every site that reads retrieval settings.

Expert has TWO retrieval sites -- _handle_simple and the retrieve_node closure inside
  _handle_with_graph. The closure captures its settings from the enclosing scope, so wiring one and
  forgetting the other leaves half the traffic silently unrouted, and the existing suite would not
  notice because it mocks PromptGraph wholesale. Added tests that capture and drive the closure
  directly, then verified they FAIL when the closure is reverted to instance constants.

Guidance applies width at TWO points: the per-collection query and the post-dedupe truncation.
  Applying the profile at only the first fetches the extra evidence and discards it at the second.
  The funnel-survival test asserts on sources that reach the answer, not on what was requested --
  verified it fails with 'complex delivered 5 sources and simple delivered 5' when the truncation
  site is left unwired.

Complex widens budget alongside width. Measured at the deployed CHUNK_SIZE 9000: simple delivers 2
  chunks, complex 4. Widening width alone would have delivered 2 and 2.

Config is off by default and validated at startup naming the offending variable. When disabled
  nothing is injected, so the plugins take their existing branch rather than a table that happens to
  agree with it.

734 passed, 89.01% coverage. The gate ran unmodified: T002 predicted a pyarrow collection abort,
  which does not occur on a clean install -- that premise came from my own earlier misdiagnosis
  (vc#112, closed as not-a-bug) and is corrected in the task file.

- **tracing**: Pipeline wiring — root handle spans, retrieval quality signals, failure taxonomy,
  ingest step spans
  ([`abcf035`](https://github.com/alkem-io/virtual-contributor/commit/abcf0351610a3f295f80ac793a1a75c572158d59))

vc.handle root spans on both ACK paths with vc.failure_mode classification
  (timeout|llm_error|empty_retrieval|parse_error|unknown); vc.retrieval spans carry
  n_returned/chunks_passed/chunks_dropped_budget + score stats; condensation wrapped in vc.stage
  query_processing; ingest engine emits one vc.ingest.step span per step mirroring StepMetrics,
  including gated skips. Callbacks attach at model construction so the prompt-graph adapter-bypass
  path is covered; disabled path constructs kwargs identically to before.

workspace#039-vc-rag-observability

- **tracing**: Zero-egress OpenTelemetry foundation — config, module-local provider, LLM callbacks,
  traced store
  ([`1ff4cea`](https://github.com/alkem-io/virtual-contributor/commit/1ff4ceaee03008b806191b3ec87e884858917a02))

Dark by default (TRACING_ENABLED=false): lazy SDK imports, no-op tracer, constructor-explicit OTLP
  endpoint/headers/sampler so ambient OTEL_* env can never redirect export (decoy-env test
  included). Content attributes gated + truncated; token usage only from provider usage_metadata.

workspace#039-vc-rag-observability

### Refactoring

- Rename ScalewayEmbeddingsAdapter to OpenAICompatibleEmbeddingsAdapter
  ([`dca8c9d`](https://github.com/alkem-io/virtual-contributor/commit/dca8c9d9334d75dd2b6d26b4a094f0123c6c32cd))

The adapter is a generic OpenAI-compatible HTTP embeddings client, not Scaleway-specific. Rename
  class, file, and references to reflect the actual API standard it implements. Remove
  vendor-specific default model name from the adapter constructor (now required).

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

### Testing

- **ingest**: Assert the label at the store boundary and the filter shape (workspace#044)
  ([`cad5470`](https://github.com/alkem-io/virtual-contributor/commit/cad547068efac8a86c99c6ffcfe0fb156ab867ea))

The remaining two review findings.

Every other assertion reads the in-memory chunk; retrieval reads stored metadata. One test now
  drives the pipeline through StoreStep and asserts a description and a post land under
  distinguishable embeddingType keys, so a change to how metadata is written cannot quietly stop the
  label arriving.

The retrieval risk had only a grep behind it. Two assertions now state the rule in the vocabulary
  itself: an exclusion-shaped predicate admits overview, and content is not the single value "chunk"
  — so a future inclusion-shaped filter, which would silently drop every space and subspace
  description from results, fails here instead of in production. Stated without importing any filter
  module, so it holds regardless of which one is used.

The short-document property is derived from the strategy table rather than a hard-coded small body,
  with the negative half asserted too. It claimed to test a property and tested a coincidence that
  would survive almost any regression.

Recorded the vocabulary and both rules in CLAUDE.md, where the next person to add a value will look.

Refs alkem-io/virtual-contributor#18

- **ingest**: Pin overview root resolution across pipeline shapes (workspace#043)
  ([`4380d2d`](https://github.com/alkem-io/virtual-contributor/commit/4380d2de633fb281e021aa2a0bdefc47f909c5d5))

The body-of-knowledge overview derives its root from the documents already collected rather than
  threading a new argument through the plugin wiring, so the resolution has to hold in every shape
  the engine builds.

Covers batched finalize (which starts with no chunks at all), a root space with no description of
  its own (which emits no root-tier document), a root document that is not first, chunk-only
  fallback, and the two cases that must stay empty rather than invent a root: website ingestion and
  an empty run.

Refs alkem-io/virtual-contributor#17

- **ingest**: Pin the overview ceiling boundary (workspace#044)
  ([`70e6e42`](https://github.com/alkem-io/virtual-contributor/commit/70e6e423fd494c0103da856a53122941cea6d9fc))

The 8,000 ceiling is below one live default: ingest_space constructs the splitter at 9,000, so a
  description between 8,001 and 9,000 characters is one passage today and becomes two. Accepted and
  now recorded rather than left to be discovered — such a description is far outside the 500-3,000
  range descriptions occupy, and the ceiling becomes strictly more permissive once the default drops
  to 2,500.

Refs alkem-io/virtual-contributor#18

- **ingest**: Pin tree position end to end (workspace#043)
  ([`8f03a8f`](https://github.com/alkem-io/virtual-contributor/commit/8f03a8f9df3f4d92f11a57309e1c063260fa50d4))

Covers the whole position table entry by entry over a fixture with root, both subspace levels,
  callouts at each level and all three contribution kinds, plus the invariants that a subspace
  implies a tier below the root and that the root never claims one.

Also pins the failure modes rather than only the happy path:

- unknown position is absent from stored metadata, never None or blank, and every stored value is a
  scalar — a None fails the whole batch it belongs to; - depth survives its falsy 0 default,
  including on website entries; - website ingestion is unchanged and fabricates nothing; - a
  document's split parts and its summary agree on one position, and the overview reports the root
  through both of its write paths; - re-ingesting the same text under a new parent rewrites the
  entry and orphans the stale one, instead of being skipped as unchanged; - a positive scope over a
  mixed corpus returns only entries carrying the key, recording the narrowing as a decision for the
  consuming stories.

Refs alkem-io/virtual-contributor#17

- **rewrite**: Pin that an injected rewrite cannot cross collection scope
  ([`e9a95f7`](https://github.com/alkem-io/virtual-contributor/commit/e9a95f7663af69e196234f088fdf866d340f9648))

- **tracing**: Acceptance suite — US1 trace trees, US4 token paths, streaming, RAGAS harness
  regression
  ([`59e59ae`](https://github.com/alkem-io/virtual-contributor/commit/59e59ae72608ebab396ffe36337f60c1b67ee9a5))

Scenario-mapped persisted acceptance specs (US1-AS1..AS3, US4-AS1..AS3, streaming single-span edge
  case) driven through the real plugin wiring with InMemorySpanExporter, incl. the expert
  prompt-graph adapter-bypass token path (risk R-7) and the evaluation-harness non-regression check
  (risk R-4).

workspace#039-vc-rag-observability
