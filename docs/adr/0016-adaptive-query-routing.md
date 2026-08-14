# 16. Adaptive query routing by rules, not by a model

Date: 2026-08-14

## Status

Accepted. Ships off by default (`ROUTING_ENABLED=false`).

## Context

Every question went through the same retrieval pipeline. "Thanks!" paid for an
embedding call and a vector search it had no use for; a comparison across two
subspaces got the same narrow slice of context as a one-line lookup.

[vc#29](https://github.com/alkem-io/virtual-contributor/issues/29) proposed
classifying each query and routing it, offering three mechanisms: **A**
rule-based heuristics, **B** an LLM classifier, **C** a fine-tuned lightweight
model. It recommended treating classification as a prerequisite for
[vc#24](https://github.com/alkem-io/virtual-contributor/issues/24) (query
transformation), whose own text says transformation "must be gated behind
adaptive routing (#29)".

Three facts about this deployment shaped the decision, each verified rather
than assumed.

**There is no GPU.** `grep -rn "nvidia.com/gpu" infrastructure-operations/`
returns nothing, in any cluster. Engine pods are limited to roughly 1.5 CPU and
2500Mi.

**Nothing runs locally.** `EMBEDDINGS_ENDPOINT` and `BOK_LLM_BASE_URL` point at
`api.scaleway.ai`; `SUMMARIZE_LLM_PROVIDER` and `ASSISTANT_LLM_PROVIDER` resolve
to Mistral. Both vc#29's Option B ("~200-500ms on local GPU") and vc#24's
acceptance criterion ("all transformation runs on local LLM — no external API
calls") describe an infrastructure that does not exist here. **Every LLM call
this service makes already leaves the boundary.**

**Plugins are separate deployments.** `PLUGIN_TYPE` is set per Deployment and
each engine consumes its own queue (`RABBITMQ_INVOKE_ENGINE_EXPERT`,
`_GUIDANCE`, `_GENERIC`); `core/registry.py` imports exactly one plugin per
process. By the time a message reaches a process, the "route" has already been
chosen by whoever published to that queue.

## Decision

**Option A — rule-based classification behind a swappable port.**

### The arithmetic rules out Option B

A classifier costs `C` on **every** query, including the simple ones it exists
to make faster. If a share `f` of traffic reaches a cheaper path saving `S`,
the feature is net-positive only when `f × S > C`, i.e. `f > C/S`:

| `C` | `S`=300ms | `S`=600ms | `S`=1200ms |
|---|---|---|---|
| 200 ms | 67% | 33% | 17% |
| 350 ms | >100% | 58% | 29% |
| 500 ms | impossible | 83% | 42% |

An LLM classifier here means a round trip to Scaleway or Mistral over the
public internet. At 500ms saving 600ms, **83% of all traffic** would have to be
simple just to break even — and `f` has never been measured for Alkemio.

Rules measured at **0.0049 ms**. With `C ≈ 0`, `f × S > C` holds for any `f > 0`,
so the decision does not depend on a number nobody has.

### Option C is unbuildable

A fine-tuned distilbert needs `torch` — multiple GB of wheels into a distroless
runtime image with a size floor (workspace#026) — a GPU that does not exist, and
labelled training data that does not exist.

### What routing can mean here

Not the story's four-row table. Cross-plugin dispatch is structurally
unavailable, and its "conversational → skip retrieval" row is **already
implemented as a separate service**: `plugins/generic/plugin.py` takes only an
`LLMPort`. Routing here is **intra-plugin** — varying retrieval width, score
threshold, context budget, and whether retrieval happens at all.

### The rules are deliberately lopsided

The four ways to be wrong are not equally bad:

| Mistake | Consequence |
|---|---|
| **real question → skip retrieval** | **answers ungrounded — user-visible harm** |
| simple → moderate/complex | slightly slower |
| complex → simple | exactly today's behaviour |
| unrecognised → simple | exactly today's behaviour |

Only the first is harmful, so only that route has a hard gate: the **whole
message** must match an anchored small-talk allow-list, contain no `?`, and be
at most six words. An earlier substring form routed *"Which subspaces exist
here?"* to skip retrieval — `hi` occurs inside `which`. Everything unmatched
falls through to a retrieving route, so **every misclassification degrades to
"retrieve anyway"**.

### No message-length rule

An ablation sweeping the threshold from 8 to 24 words showed length contributes
**exactly zero** accuracy while misrouting verbose-but-trivial lookups
("could you please just tell me what the name of the lead of this space is") to
the expensive route. Length tracks how elaborately someone writes, not how hard
the question is. Removed, and pinned by a test so it is not reintroduced as an
apparent improvement.

### Width and budget move together

At the deployed `CHUNK_SIZE=9000`, the existing 20000-character context budget
admits only **two** chunks — so widening `n_results` alone changes nothing that
reaches the model. A "complex" route that widened retrieval without widening the
budget would look implemented and do nothing. Each profile therefore states
both, and a test asserts the *effective* chunk count is strictly greater for
complex at both the 2000- and 9000-character chunk sizes.

## Consequences

- Classification is free, local, and adds no dependency. Asserted by a
  sub-millisecond bound, a socket-poisoned runtime test, and an import scan
  applied to **every** implementation of the port — not just the shipped one,
  because pinning the module would leave the seam unguarded.
- Off by default. Disabled, nothing is injected and both plugins take their
  pre-existing branch, so the rollback is a config change.
- **vc#24 plugs into this seam.** Query transformation becomes another
  per-route decision, gated exactly as vc#24 asks. Note that its "local LLM"
  criterion cannot be met as written — see the context above — and that should
  be settled before it is built.
- Only two of the story's routing behaviours exist on develop today: skip
  retrieval, and scale depth. The richer paths arrive with vc#24, #114 and #115.
- Rules are English-only; other languages fall through to retrieval. The
  failure mode is "no benefit", not "wrong answer".
- `f` remains unmeasured. The chosen route is logged so it can be measured
  before anything is tuned.
