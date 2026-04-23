# Implementation Plan: Automated Semantic Release Pipeline

**Branch**: `030-semantic-release` | **Date**: 2026-04-23 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/030-semantic-release/spec.md`

## Summary

Automates versioning and release publishing using `python-semantic-release`. On merge to `main`, a new GitHub Actions workflow analyzes conventional commits, bumps the version in `pyproject.toml`, creates a git tag and GitHub Release. The existing Build workflow is updated to distinguish between dev pushes (ghcr.io) and release events (Docker Hub), ensuring production images are published to Docker Hub with semantic version tags.

## Technical Context

**Language/Version**: Python 3.12
**Primary Dependencies**: python-semantic-release v9 (GitHub Action), Docker
**Storage**: N/A
**Testing**: Manual verification via GitHub Actions runs
**Target Platform**: GitHub Actions CI/CD
**Project Type**: CI/CD pipeline configuration
**Performance Goals**: Release pipeline completes within 5 minutes
**Constraints**: Must not disrupt existing develop-branch CI flow
**Scale/Scope**: Single repository, single Docker image

## Constitution Check

| Principle/Standard | Status | Notes |
|---|---|---|
| P1 AI-Native Development | PASS | Enables zero-touch release — merging to main triggers fully automated versioning and publishing |
| P2 SOLID Architecture | N/A | CI/CD configuration, not application code |
| P3 No Vendor Lock-in | N/A | CI/CD tooling choice, not application architecture |
| P4 Optimised Feedback Loops | PASS | Automates release feedback — developers see releases created automatically within minutes of merge |
| P5 Best Available Infrastructure | PASS | Uses standard GitHub Actions runners (ubuntu-latest) |
| P6 Spec-Driven Development | PASS | This retrospec documents the feature |
| P7 No Filling Tests | N/A | No application tests involved — CI/CD config changes |
| P8 Architecture Decision Records | N/A | No architectural change to the application — CI/CD pipeline setup |
| Single Image, Multiple Deployments | PASS | Preserves single Dockerfile, single image. Only changes where/when it's pushed |
| Event Schema as Wire Contract | N/A | No event schema changes |

## Project Structure

### Documentation (this feature)

```text
specs/030-semantic-release/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── tasks.md
└── checklists/
    └── requirements.md
```

### Source Code (repository root)

```text
.github/workflows/
├── build.yml          # Modified: split registry auth, release-event trigger
└── release.yml        # New: semantic-release workflow
pyproject.toml         # Modified: added [tool.semantic_release] config
CLAUDE.md              # Modified: added Commit Conventions section
```

**Structure Decision**: Changes are confined to CI/CD configuration and documentation. No application source code is modified.

## Complexity Tracking

No constitution violations — this section is not applicable.
