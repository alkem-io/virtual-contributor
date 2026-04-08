---
description: Triage all CodeRabbit review comments on a single PR, addressing or declining each one autonomously. Normally invoked by the PostToolUse hook one hour after PR open; can also be run manually with a PR URL.
allowed-tools: Task, Bash, Read
---

# SDD CodeRabbit Triage

You triage CodeRabbit review comments for one pull request. You do not triage yourself — you dispatch the work to the `sdd-triage-worker` subagent and report its result.

## Arguments

`$ARGUMENTS` is a single full GitHub PR URL, e.g. `https://github.com/alkem-io/server/pull/1234`.

If `$ARGUMENTS` is empty or not a valid PR URL, exit with an error immediately. Do not prompt the user — this command is invoked unattended by a hook and a prompt would hang it.

## Flow

1. Validate the PR URL.
2. Dispatch a `sdd-triage-worker` subagent via the Task tool, passing `PR_URL=$ARGUMENTS`.
3. When the subagent returns, print its summary verbatim and exit.

## Rules

- Fully hands-free. Never prompt.
- Single subagent per invocation. No fan-out at this level — one command run = one PR.
- Do not touch the worktree yourself. The subagent owns it.
