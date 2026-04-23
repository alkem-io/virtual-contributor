# Research: Automated Semantic Release Pipeline

**Feature Branch**: `030-semantic-release`
**Date**: 2026-04-23

## Decision Summary

| # | Decision | Rationale | Impact |
|---|----------|-----------|--------|
| D1 | Use `python-semantic-release` over `semantic-release` (Node.js) | Python project — keeps tooling in the same ecosystem, reads version from `pyproject.toml` natively | Low risk — well-maintained, v9 is stable |
| D2 | Trigger Build on `release` event, not `tags` | Decouples build from tag creation mechanics; `release` event is the semantic signal that a version is ready for production | Cleaner separation of concerns |
| D3 | Dual registry strategy (ghcr.io for dev, Docker Hub for releases) | Dev images are internal (ghcr.io is free for GitHub repos), production images go to Docker Hub where operators expect them | Requires two sets of credentials |
| D4 | Use `RELEASE_TOKEN` instead of `GITHUB_TOKEN` for semantic-release | `GITHUB_TOKEN` cannot trigger other workflows (GitHub limitation). A PAT or fine-grained token in `RELEASE_TOKEN` allows the Release workflow's tag/release to trigger the Build workflow | Critical for the release→build chain |
| D5 | Document conventions in CLAUDE.md rather than enforce via commit-msg hook | CLAUDE.md is read by AI agents (the primary developers). A hook would add friction without adding value since agents already follow instructions | Relies on convention, not enforcement |

## Detailed Decisions

### D1: python-semantic-release over Node.js semantic-release

**Decision**: Use `python-semantic-release/python-semantic-release@v9` GitHub Action.

**Rationale**: This is a Python project managed with Poetry. `python-semantic-release` natively understands `pyproject.toml` and can update `tool.poetry.version` directly. The Node.js `semantic-release` would require additional plugins and configuration to handle Python versioning.

**Alternatives considered**:
- **Node.js semantic-release**: More widely adopted, but requires Node.js in the CI environment and custom plugins for Python version files. Adds ecosystem complexity.
- **Manual versioning with `bump2version`**: Would still require manual intervention to decide version bumps, defeating the automation goal.
- **GitHub Actions release drafter**: Only drafts release notes, doesn't handle version bumping or tagging.

### D2: Release event trigger instead of tag-based trigger

**Decision**: The Build workflow triggers on `release: types: [published]` instead of `push: tags: ["v*"]`.

**Rationale**: The `release` event is a higher-level semantic signal. It fires after `python-semantic-release` has created both the tag AND the GitHub Release. A tag-based trigger would fire on any tag push, including manual or accidental tags.

**Alternatives considered**:
- **Tag-based trigger (`push: tags: ["v*"]`)**: The previous approach. Less precise — any tag matching `v*` triggers a build, even manual tags not associated with a release.
- **Workflow dispatch**: Would require manual triggering, defeating automation.

### D3: Dual registry strategy

**Decision**: Push dev images to ghcr.io, production images to Docker Hub.

**Rationale**: ghcr.io is tightly integrated with GitHub (free for public repos, automatic auth). Docker Hub is where the Alkemio operations team pulls production images. Separating them prevents dev images from cluttering the production registry.

**Alternatives considered**:
- **Single registry (Docker Hub only)**: Would push dev images to Docker Hub, consuming rate limits and mixing dev/prod images.
- **Single registry (ghcr.io only)**: Would require operators to change their pull source from Docker Hub.

### D4: Dedicated RELEASE_TOKEN secret

**Decision**: Use `secrets.RELEASE_TOKEN` (a PAT or fine-grained token) for the semantic-release step.

**Rationale**: GitHub's default `GITHUB_TOKEN` cannot trigger other workflows. Since the Release workflow creates a GitHub Release that must trigger the Build workflow, a token with broader permissions is required.

**Alternatives considered**:
- **GITHUB_TOKEN**: Simplest option but would break the release→build chain due to GitHub's recursive workflow prevention.
- **GitHub App token**: More secure but more complex to set up. Could be adopted later if PAT rotation becomes a concern.

### D5: Convention over enforcement for commit messages

**Decision**: Document conventional commit format in CLAUDE.md rather than adding a `commitlint` or `commit-msg` hook.

**Rationale**: The primary contributors are AI agents that read CLAUDE.md as their operating instructions. A git hook would add CI complexity without improving compliance for the primary audience. `python-semantic-release` gracefully handles non-conventional commits by simply not creating a release.

**Alternatives considered**:
- **commitlint + husky**: Standard approach for human teams. Adds Node.js dev dependency and pre-commit hook complexity.
- **Pre-commit hook with a regex check**: Lighter weight but still adds friction for no gain when agents already follow CLAUDE.md.
