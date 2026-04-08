---
description: Generate single-responsibility SDD specs from current code changes. Decomposes multi-concern changesets into one spec per responsibility, each with all SDD artifacts.
handoffs:
  - label: Analyze Specs for Consistency
    agent: speckit.analyze
    prompt: Run a project analysis for consistency across the generated specs
    send: true
---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty). The user may specify:
- A custom diff range (e.g., `origin/develop..HEAD`, `HEAD~3`)
- A list of files to focus on
- Hints about how to decompose responsibilities
- `--dry-run` to only show the proposed decomposition without generating artifacts

## Outline

### Step 1: Determine the Change Set

Determine what "current changes" means based on context:

1. **If `$ARGUMENTS` specifies a diff range** (e.g., `origin/develop..HEAD`, `HEAD~5`, a commit SHA): use that range.
2. **If there are uncommitted changes** (staged or unstaged): use `git diff HEAD` to capture all working-tree changes.
3. **If the current branch differs from the main branch** (typically `develop` or `main`): use `git diff $(git merge-base HEAD develop)..HEAD` to capture all branch changes.
4. **If none of the above produce changes**: ERROR "No changes detected. Specify a diff range as argument."

Run `git status` and the appropriate `git diff` (with `--stat` first for overview, then full diff). Also run `git log --oneline` for the relevant range to understand commit history.

### Step 2: Read and Understand All Changed Files

For each file in the changeset:
1. Read the **full current content** of the file (not just the diff) to understand context.
2. Read the **diff hunks** to understand what specifically changed.
3. Note the file's role in the architecture (core/, plugins/, tests/, config, etc.) using CLAUDE.md as reference.

### Step 3: Decompose into Single-Responsibility Concerns

Analyze all changes and group them into **distinct, single-responsibility concerns**. Each concern should:
- Address **one cohesive feature, fix, or improvement**
- Be independently understandable and testable
- Map to a clear user-facing or operator-facing value proposition

**Decomposition heuristics**:
- Changes to the same domain concept (e.g., "config validation" vs. "new pipeline step") are separate concerns
- Changes that serve the same user story belong together even if spread across files
- Infrastructure/plumbing changes that enable a feature belong WITH that feature, not as a separate spec
- Test changes belong with the production code they test

**If all changes serve a single responsibility**: create exactly one spec.
**If multiple responsibilities are detected**: create one spec per responsibility, clearly delineating which files/changes belong to each.

Present the proposed decomposition to the user in this format before generating artifacts:

```markdown
## Proposed Decomposition

### Spec 1: [Short Title]
**Responsibility**: [One-sentence description]
**Files**:
- `path/to/file1.py` — [what changed and why]
- `path/to/file2.py` — [what changed and why]

### Spec 2: [Short Title]
**Responsibility**: [One-sentence description]
**Files**:
- `path/to/file3.py` — [what changed and why]

Proceed with generating specs? (Y/n)
```

Wait for user confirmation unless `$ARGUMENTS` contains `--yes` or `-y`. If `--dry-run` was specified, stop here.

### Step 4: Determine Spec Numbering and Create Worktrees

For each spec to be created:

1. Look at existing `specs/` directories to find the highest sequential number.
2. Also check git branches for the highest feature number.
3. Assign the next sequential number(s): if creating 2 specs and highest existing is `008`, use `009` and `010`.
4. Generate a short name (2-4 words, kebab-case) for each spec from its responsibility title.
5. **Create a git worktree and branch** for each spec:
   ```bash
   git worktree add ../worktrees/NNN-short-name -b NNN-short-name HEAD
   ```
6. **Apply only the relevant code changes** to each worktree. For each spec, apply only the diff hunks that belong to that spec's responsibility. Use targeted file edits in the worktree — do not copy the full modified files from the main working tree (they contain changes from other specs). Use subagents in parallel (one per worktree) to apply changes concurrently.

### Step 5: Generate All SDD Artifacts

For each spec, working **inside its worktree**, create the directory `specs/NNN-short-name/` and generate ALL of the following artifacts. Each artifact must be populated with concrete content derived from the actual code changes — not templates or placeholders.

#### 5.1: spec.md (Feature Specification)

Generate using the structure from `.specify/templates/spec-template.md`:

```markdown
# Feature Specification: [FEATURE NAME]

**Feature Branch**: `[current-branch-name]`
**Created**: [TODAY'S DATE]
**Status**: Implemented
**Input**: Retrospec from code changes
```

**Mandatory sections**:
- **User Scenarios & Testing**: Derive user stories from what the code changes accomplish. Prioritize by impact (P1, P2, P3). Each story must have acceptance scenarios derived from the actual behavior the code implements. Mark priorities based on which changes are most impactful.
- **Requirements**: Derive functional requirements (FR-001, FR-002...) from what the code actually does. Each requirement must be a concrete, testable statement about system behavior.
- **Success Criteria**: Derive measurable outcomes from the implemented behavior.
- **Assumptions**: Document any assumptions implicit in the implementation.

**Key principle**: Write the spec as if it were written BEFORE implementation. It should read naturally as a specification, not as a code description. Use business/user language, not implementation language.

#### 5.2: plan.md (Implementation Plan)

Generate using the structure from `.specify/templates/plan-template.md`:

```markdown
# Implementation Plan: [FEATURE NAME]

**Branch**: `[current-branch-name]` | **Date**: [TODAY] | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/NNN-short-name/spec.md`
```

Include:
- **Summary**: What the feature does and the technical approach taken.
- **Technical Context**: Fill from the actual project (Python 3.12, Poetry, pytest, etc.).
- **Constitution Check**: Evaluate the changes against `.specify/memory/constitution.md`. For each principle/standard, mark PASS/FAIL/N/A with notes.
- **Project Structure**: Show the actual files changed (documentation tree + source code tree).
- **Complexity Tracking**: Only if constitution violations exist.

#### 5.3: research.md (Research Decisions)

Document the technical decisions embodied in the code:

```markdown
# Research: [FEATURE NAME]

**Feature Branch**: `[current-branch-name]`
**Date**: [TODAY]
```

For each significant technical decision visible in the code:
- **Decision**: What was chosen
- **Rationale**: Why (infer from code patterns, comments, architecture)
- **Alternatives considered**: What other approaches could have been taken

Include a summary table of all decisions.

#### 5.4: data-model.md (Data Model)

Document any data model changes:

```markdown
# Data Model: [FEATURE NAME]

**Feature Branch**: `[current-branch-name]`
**Date**: [TODAY]
```

Include:
- New or modified entities (Pydantic models, config fields, domain objects)
- Field types, defaults, validation rules
- Relationships between entities
- State transitions if applicable

If no data model changes exist, write a brief note explaining that and skip the detailed sections.

#### 5.5: contracts/ (Interface Contracts)

Only generate if the changes affect external interfaces (ports, event schemas, HTTP endpoints, plugin contract). For each affected contract:
- Document the interface before and after
- Note backward compatibility implications

If no contract changes exist, skip this directory entirely.

#### 5.6: quickstart.md (Quickstart Guide)

```markdown
# Quickstart: [FEATURE NAME]

**Feature Branch**: `[current-branch-name]`
**Date**: [TODAY]
```

Include:
- What the feature does (brief)
- Any new environment variables or configuration
- How to verify the feature works (concrete steps)
- Files changed (table)

#### 5.7: tasks.md (Task Breakdown)

Generate using the structure from `.specify/templates/tasks-template.md`. Since the code is already implemented, **all tasks MUST be marked as complete** with `[X]`.

```markdown
# Tasks: [FEATURE NAME]

**Input**: Design documents from `specs/NNN-short-name/`
**Organization**: Tasks grouped by user story.
```

Follow the exact task format:
- `- [X] T001 [P?] [Story?] Description with file path`
- Use the standard phase structure (Foundational, User Story phases, Polish)
- Include dependency information and parallel opportunities
- Each user story phase must reference the spec's user stories

#### 5.8: checklists/requirements.md (Specification Quality Checklist)

```markdown
# Specification Quality Checklist: [FEATURE NAME]

**Purpose**: Validate specification completeness and quality
**Created**: [TODAY]
**Feature**: [spec.md](../spec.md)
```

Evaluate the generated spec against the standard quality criteria. Mark items as checked `[X]` where the spec passes, unchecked `[ ]` where it has gaps.

### Step 6: Report

After generating all specs, report:

```markdown
## Retrospec Complete

### Generated Specs

| # | Spec | Worktree | Branch | Files | Lines |
|---|------|----------|--------|-------|-------|
| 1 | [Title] | `../worktrees/NNN-short-name/` | `NNN-short-name` | N changed + spec dir | +X / -Y |
| 2 | [Title] | `../worktrees/NNN-short-name/` | `NNN-short-name` | N changed + spec dir | +X / -Y |

### Change Coverage

- **Files covered**: N/N files from the changeset are accounted for in specs
- **Uncovered files**: [list any files not assigned to a spec, with reason]

### Next Steps

- Review generated specs for accuracy
- Run `/speckit.analyze` for cross-artifact consistency check
- Commit, push, and open PRs from each worktree
```

## Key Rules

- **Single Responsibility**: Each spec MUST cover exactly one cohesive concern. When in doubt, split.
- **Concrete, not template**: Every artifact must contain real content from the actual code changes. No placeholder text, no template markers, no `[FILL IN]` items.
- **Retrospective voice**: Write specs as if they were written before implementation, but informed by what was actually built. They should read as natural specifications.
- **Complete artifact set**: Every spec gets spec.md, plan.md, research.md, data-model.md, quickstart.md, tasks.md, and checklists/requirements.md. Skip contracts/ only when no external interfaces changed.
- **Tasks are complete**: All tasks in tasks.md are marked `[X]` because the code already exists.
- **Worktree-isolated delivery**: Each spec MUST be created in its own git worktree with its own branch (`git worktree add ../worktrees/NNN-short-name -b NNN-short-name HEAD`). Only that spec's code changes and spec directory are applied to the worktree. The decomposition MUST ensure that each spec's file set is self-contained — a spec's changes must be cherry-pickable or applicable independently without requiring changes from another spec. If two concerns share a file, either co-locate them in one spec or split the file changes so each spec's portion is independently viable. Use parallel subagents to apply changes to worktrees concurrently.
- **Constitution awareness**: The plan.md must include a constitution check against `.specify/memory/constitution.md`.
- **Preserve existing numbering**: Spec numbers continue sequentially from the highest existing spec number.
