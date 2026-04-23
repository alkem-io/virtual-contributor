# Tasks: Automated Semantic Release Pipeline

**Input**: Design documents from `specs/030-semantic-release/`
**Organization**: Tasks grouped by user story.

## Phase 1: Foundational (Blocking Prerequisites)

**Purpose**: Configuration that all user stories depend on

- [X] T001 [US1] Add `[tool.semantic_release]` configuration block to `pyproject.toml` with version source, branch, commit message template, and empty build command
- [X] T002 [US1] Document conventional commit prefixes and version bump mapping in `CLAUDE.md` under "Commit Conventions" section

**Checkpoint**: Semantic release configuration is in place

---

## Phase 2: User Story 1 - Automated Version Bumps on Merge to Main (Priority: P1)

**Goal**: Push to `main` triggers automatic version bump, tag, and GitHub Release

**Independent Test**: Merge a `fix:` commit to `main` and verify a GitHub Release is created

### Implementation for User Story 1

- [X] T003 [US1] Create `.github/workflows/release.yml` with `push: branches: [main]` trigger, checkout with `fetch-depth: 0`, Python 3.12 setup, and `python-semantic-release/python-semantic-release@v9` action using `RELEASE_TOKEN`
- [X] T004 [US1] Set `permissions: contents: write` in release workflow to allow tag and release creation

**Checkpoint**: Merges to main now auto-create releases

---

## Phase 3: User Story 2 - Docker Hub Publishing on Release (Priority: P1)

**Goal**: GitHub Release publication triggers Docker image push to Docker Hub

**Independent Test**: Publish a GitHub Release and verify Docker Hub image

### Implementation for User Story 2

- [X] T005 [US2] Add `release: types: [published]` trigger to `.github/workflows/build.yml`
- [X] T006 [US2] Add "Log in to Docker Hub" step conditional on `github.event_name == 'release'` using `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` secrets
- [X] T007 [US2] Update Docker metadata `images` to use `alkemio/virtual-contributor` for release events
- [X] T008 [US2] Add `type=raw,value=latest,enable=${{ github.event_name == 'release' }}` tag to metadata

**Checkpoint**: Releases now publish Docker images to Docker Hub with version + latest tags

---

## Phase 4: User Story 3 - Dev Image Publishing on Push to Develop (Priority: P2)

**Goal**: Dev pushes continue to work via ghcr.io without regression

**Independent Test**: Push to develop and verify ghcr.io image

### Implementation for User Story 3

- [X] T009 [US3] Update push trigger branches from `[develop, main]` to `[develop]` in `.github/workflows/build.yml`
- [X] T010 [US3] Remove old single "Log in to registry" step and add "Log in to ghcr.io" step conditional on `github.event_name == 'push'` using `ghcr.io` registry, `github.actor`, and `GITHUB_TOKEN`
- [X] T011 [US3] Update Docker metadata `images` to use `ghcr.io/alkemio/virtual-contributor` for push events via format function

**Checkpoint**: Dev workflow preserved — pushes to develop still build and push to ghcr.io

---

## Dependencies & Execution Order

### Phase Dependencies

- **Foundational (Phase 1)**: No dependencies — configuration setup
- **User Story 1 (Phase 2)**: Depends on Phase 1 (needs semantic_release config)
- **User Story 2 (Phase 3)**: Depends on Phase 2 (needs releases to exist to trigger builds)
- **User Story 3 (Phase 4)**: Independent of other stories — preserves existing behavior

### Parallel Opportunities

- T001 and T002 can run in parallel (different files)
- T005, T006, T007, T008 all modify `build.yml` — must be sequential
- T009, T010, T011 also modify `build.yml` — must be sequential with Phase 3 tasks
- User Story 3 is independent and could be implemented in parallel with User Story 2
