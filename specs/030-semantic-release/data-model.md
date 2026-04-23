# Data Model: Automated Semantic Release Pipeline

**Feature Branch**: `030-semantic-release`
**Date**: 2026-04-23

## Overview

This feature does not introduce or modify any application data models (Pydantic models, domain objects, or database schemas). All changes are to CI/CD configuration files and documentation.

The only structured data involved is the `[tool.semantic_release]` configuration block in `pyproject.toml`, which is a standard TOML configuration section consumed by the `python-semantic-release` tool:

| Field | Type | Value | Purpose |
|-------|------|-------|---------|
| `version_toml` | list[str] | `["pyproject.toml:tool.poetry.version"]` | Tells semantic-release where to read/write the version |
| `branch` | str | `"main"` | The branch on which releases are created |
| `commit_message` | str | `"chore(release): {version}"` | Template for the version bump commit message |
| `build_command` | str | `""` | No build step needed (Docker build is handled by the Build workflow) |

No entity relationships, state transitions, or validation rules are affected.
