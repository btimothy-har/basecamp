#!/usr/bin/env bash
# Detect the git repo name and create PR workflow directories.
#
# Exports GIT_REPO via CLAUDE_ENV_FILE so bc-eng skills can reference it
# without depending on basecamp launch. Falls back to the working directory
# basename when not inside a git repository.

set -euo pipefail

# Detect repo name from git, fall back to directory basename
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  GIT_REPO=$(basename "$(git rev-parse --show-toplevel)")
else
  GIT_REPO=$(basename "$PWD")
fi

# Export for subsequent Bash tool calls
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  printf 'export GIT_REPO=%s\n' "'$GIT_REPO'" >> "$CLAUDE_ENV_FILE"
fi

# Create PR workflow directories
SCRATCH="/tmp/claude-workspace/$GIT_REPO"
mkdir -p "$SCRATCH/pull_requests"
mkdir -p "$SCRATCH/pr-comments"
