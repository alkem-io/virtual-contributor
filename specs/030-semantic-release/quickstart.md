# Quickstart: Automated Semantic Release Pipeline

**Feature Branch**: `030-semantic-release`
**Date**: 2026-04-23

## What It Does

Automates version bumping, git tagging, GitHub Release creation, and Docker Hub image publishing. When commits with conventional prefixes (`fix:`, `feat:`, `feat!:`) are merged to `main`, `python-semantic-release` determines the version bump, and the Build workflow publishes the Docker image to Docker Hub.

## Prerequisites

Configure these GitHub repository secrets:

| Secret | Purpose |
|--------|---------|
| `RELEASE_TOKEN` | PAT or fine-grained token with `contents: write` permission — used by semantic-release to create tags and releases |
| `DOCKERHUB_USERNAME` | Docker Hub username for image publishing |
| `DOCKERHUB_TOKEN` | Docker Hub access token for image publishing |

## How to Verify

1. **Release workflow**: Push a `fix:` commit to `main` (via merged PR). Check the Actions tab — the "Release" workflow should run and create a new GitHub Release with a patch version bump.
2. **Build workflow**: After the Release is published, the "Build & Push" workflow should trigger automatically and push the image to Docker Hub.
3. **Dev workflow**: Push to `develop` — the "Build & Push" workflow should push to ghcr.io as before.

## Commit Message Format

| Prefix | Effect |
|--------|--------|
| `fix:` | Patch bump (0.1.0 → 0.1.1) |
| `feat:` | Minor bump (0.1.0 → 0.2.0) |
| `feat!:` or `BREAKING CHANGE:` footer | Major bump (0.1.0 → 1.0.0) |
| `chore:`, `docs:`, `ci:`, `test:`, `refactor:` | No release |

## Files Changed

| File | Change |
|------|--------|
| `.github/workflows/release.yml` | New — semantic-release workflow on push to main |
| `.github/workflows/build.yml` | Modified — dual registry auth, release event trigger |
| `pyproject.toml` | Modified — added `[tool.semantic_release]` config |
| `CLAUDE.md` | Modified — added Commit Conventions documentation |
