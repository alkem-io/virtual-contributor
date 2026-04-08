---
description: Fan out a full hands-free SDD flow across every open story in a GitHub epic, one subagent per story, strict SpecKit, YOLO mode, CodeRabbit triage included.
allowed-tools: Bash, Task, Read
---

# SDD Epic Orchestrator

You are orchestrating autonomous Spec-Driven Development across every open story in a GitHub epic. You delegate each story to a fresh `sdd-story-worker` subagent and aggregate the results. You do not execute SDD work yourself.

## Arguments

`$ARGUMENTS` is expected in the form:

```
<owner>/<repo>#<epic-issue-number> [base-branch] [concurrency]
```

Defaults: `base-branch=develop`, `concurrency=4`.

## Phase 0 — Epic expansion

1. Parse `$ARGUMENTS` into `EPIC`, `BASE_BRANCH`, `CONCURRENCY`.
2. Use `gh` to fetch the epic and enumerate every linked child issue that is (a) open and (b) not already associated with an open PR. These are the **stories**.
3. For each story, capture the full payload: number, title, body, labels, acceptance criteria, linked design docs. Do **not** summarize or rewrite — the subagent must see the raw issue.

## Phase 1 — Fan out

For each story, dispatch a `sdd-story-worker` subagent via the Task tool, passing:

- `STORY_NUMBER`
- `STORY_PAYLOAD` (raw, verbatim)
- `BASE_BRANCH`

Keep at most `CONCURRENCY` Task calls in flight at once. As each finishes, dispatch the next. Do not block the entire queue on one slow subagent — if one fails terminally, mark it and continue.

## Phase 2 — Aggregate

When all subagents have reported, print a final summary table:

| Story | PR | Clarify loops | Analyze loops | CR addressed | CR declined | Status |
|-------|----|--------------:|--------------:|-------------:|------------:|--------|

Then print a one-line overall verdict: how many stories landed green, how many are broken or blocked.

## Hard rules

- You never run `/speckit.*`, `/worktree`, or `gh pr create` yourself. Those belong to the subagent.
- You never ask the user for confirmation. This command is fully hands-free.
- You never mutate the orchestrator's own working directory — all file work happens inside subagent worktrees.
