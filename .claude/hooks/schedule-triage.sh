#!/usr/bin/env bash
# .claude/hooks/schedule-triage.sh
#
# PostToolUse hook. Fires on every Bash tool call (including subagent Bash calls).
# If the call was `gh pr create`, extracts the PR URL from the output and
# schedules `/sdd-triage <url>` to run headlessly via `claude -p` one hour later.
#
# Requires: jq, at, claude (in PATH).

set -euo pipefail

INPUT=$(cat)

# Extract the bash command. Bail silently if not a Bash tool call.
CMD=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty')
if [ -z "$CMD" ]; then
  exit 0
fi

# Only proceed if this invocation included `gh pr create`.
if ! printf '%s' "$CMD" | grep -qE '(^|[^a-zA-Z0-9_-])gh[[:space:]]+pr[[:space:]]+create([^a-zA-Z0-9_-]|$)'; then
  exit 0
fi

# Extract the PR URL from the tool's stdout. gh pr create prints the URL on
# completion. tool_response shape varies; try a few common paths.
STDOUT=$(printf '%s' "$INPUT" | jq -r '
  .tool_response.stdout //
  .tool_response.output //
  (.tool_response | if type == "string" then . else empty end) //
  ""
')

PR_URL=$(printf '%s' "$STDOUT" \
  | grep -oE 'https://github\.com/[^[:space:]/]+/[^[:space:]/]+/pull/[0-9]+' \
  | head -n1 || true)

if [ -z "$PR_URL" ]; then
  # gh pr create ran but we couldn't find a URL in its output. Don't fail the
  # hook — just log and exit. PostToolUse non-zero exits can surface noise.
  printf '[schedule-triage] no PR URL found in gh pr create output\n' >&2
  exit 0
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
LOG_DIR="$PROJECT_DIR/.claude/triage-logs"
mkdir -p "$LOG_DIR"

# Slugify the URL for a stable log filename.
SLUG=$(printf '%s' "$PR_URL" | sed 's|[^a-zA-Z0-9]|_|g')
LOG_FILE="$LOG_DIR/${SLUG}.log"
MARKER_FILE="$LOG_DIR/${SLUG}.scheduled"

# Idempotency: if we already scheduled triage for this PR in this session, skip.
if [ -f "$MARKER_FILE" ]; then
  exit 0
fi

# Build the deferred command. Run claude headlessly in the project dir.
# --dangerously-skip-permissions keeps the deferred run fully hands-free.
DEFERRED_CMD="cd '$PROJECT_DIR' && claude -p '/sdd-triage $PR_URL' --dangerously-skip-permissions"

if ! command -v at >/dev/null 2>&1; then
  printf '[schedule-triage] `at` not installed; cannot schedule triage for %s\n' "$PR_URL" >&2
  exit 0
fi

printf '%s >> %q 2>&1\n' "$DEFERRED_CMD" "$LOG_FILE" | at now + 1 hour 2>>"$LOG_FILE" || {
  printf '[schedule-triage] failed to schedule at job for %s\n' "$PR_URL" >&2
  exit 0
}

touch "$MARKER_FILE"
printf '[schedule-triage] scheduled triage for %s in 1 hour (log: %s)\n' "$PR_URL" "$LOG_FILE" >&2
exit 0
