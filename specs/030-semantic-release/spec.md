# Feature Specification: Automated Semantic Release Pipeline

**Feature Branch**: `030-semantic-release`
**Created**: 2026-04-23
**Status**: Implemented
**Input**: Retrospec from code changes

## User Scenarios & Testing

### User Story 1 - Automated Version Bumps on Merge to Main (Priority: P1)

As a developer, when I merge a PR to `main` with conventional commit messages, the system automatically determines the correct version bump (patch/minor/major), updates `pyproject.toml`, creates a git tag, and publishes a GitHub Release — with zero manual intervention.

**Why this priority**: This is the core value proposition — eliminating manual versioning and release creation, enabling the AI-native zero-touch delivery pipeline (Constitution P1).

**Independent Test**: Merge a commit with prefix `fix:` to `main` and verify a patch release is created automatically.

**Acceptance Scenarios**:

1. **Given** a PR with a `fix:` commit is merged to `main`, **When** the Release workflow runs, **Then** `python-semantic-release` bumps the patch version, tags the commit, and creates a GitHub Release.
2. **Given** a PR with a `feat:` commit is merged to `main`, **When** the Release workflow runs, **Then** the minor version is bumped.
3. **Given** a PR with a `feat!:` commit or `BREAKING CHANGE:` footer is merged to `main`, **When** the Release workflow runs, **Then** the major version is bumped.
4. **Given** a PR with only `chore:`, `docs:`, or `ci:` commits is merged to `main`, **When** the Release workflow runs, **Then** no release is created.

---

### User Story 2 - Docker Hub Publishing on Release (Priority: P1)

As an operator, when a GitHub Release is published, the Build workflow automatically builds and pushes the Docker image to Docker Hub (not ghcr.io), tagged with the semantic version and `latest`.

**Why this priority**: Production deployments pull from Docker Hub. Without this, releases don't reach production infrastructure.

**Independent Test**: Publish a GitHub Release and verify the Docker image appears on Docker Hub with the correct version tag and `latest`.

**Acceptance Scenarios**:

1. **Given** a GitHub Release is published, **When** the Build workflow triggers, **Then** it authenticates to Docker Hub using `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` secrets and pushes the image as `alkemio/virtual-contributor:<version>`.
2. **Given** a GitHub Release is published, **When** the Build workflow completes, **Then** the image is also tagged as `alkemio/virtual-contributor:latest`.

---

### User Story 3 - Dev Image Publishing on Push to Develop (Priority: P2)

As a developer, when I push to `develop`, the Build workflow pushes a dev image to ghcr.io (not Docker Hub), preserving the existing dev workflow.

**Why this priority**: Dev images enable testing in staging environments before release, but this is the pre-existing behavior being preserved, not new functionality.

**Independent Test**: Push a commit to `develop` and verify the image appears on ghcr.io with the branch tag.

**Acceptance Scenarios**:

1. **Given** a push to `develop`, **When** the Build workflow triggers, **Then** it authenticates to ghcr.io using `GITHUB_TOKEN` and pushes the image as `ghcr.io/alkemio/virtual-contributor:develop`.
2. **Given** a push to `develop`, **When** the Build workflow triggers, **Then** it does NOT authenticate to Docker Hub or push there.

---

### Edge Cases

- What happens when `RELEASE_TOKEN` secret is missing? The Release workflow fails with a clear authentication error.
- What happens when `DOCKERHUB_USERNAME` or `DOCKERHUB_TOKEN` secrets are missing? The Build workflow fails on the Docker Hub login step only for release events; develop pushes are unaffected.
- What happens when a release commit has no conventional commit prefix? `python-semantic-release` skips the release (no version bump).

## Requirements

### Functional Requirements

- **FR-001**: System MUST run `python-semantic-release` on every push to `main` to analyze conventional commits and determine version bumps.
- **FR-002**: System MUST update the version in `pyproject.toml` (at `tool.poetry.version`) when a release is triggered.
- **FR-003**: System MUST create a git tag and GitHub Release for each version bump.
- **FR-004**: System MUST use `chore(release): {version}` as the release commit message format.
- **FR-005**: Build workflow MUST authenticate to Docker Hub and push images when triggered by a `release` event.
- **FR-006**: Build workflow MUST authenticate to ghcr.io and push images when triggered by a `push` event to `develop`.
- **FR-007**: Release-triggered builds MUST tag images with the semantic version and `latest`.
- **FR-008**: The `CLAUDE.md` documentation MUST describe conventional commit prefixes and their version bump effects.

## Success Criteria

### Measurable Outcomes

- **SC-001**: A `fix:` commit merged to `main` produces a patch release within 5 minutes with no human intervention.
- **SC-002**: Docker Hub contains the correct versioned image after each release.
- **SC-003**: Dev pushes to `develop` continue to produce ghcr.io images without regression.
- **SC-004**: Zero manual version bumps or tag creation required for standard releases.

## Assumptions

- The `RELEASE_TOKEN` GitHub secret has sufficient permissions (`contents: write`) to create tags, commits, and releases.
- `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` secrets are configured in the repository settings.
- The `main` branch is protected and receives changes only via merged PRs from `develop`.
- Conventional commit format is enforced by team convention (documented in CLAUDE.md) rather than by a commit-msg hook.
