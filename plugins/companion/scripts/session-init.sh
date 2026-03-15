#!/bin/bash
# Exposes CLAUDE_SESSION_ID to the Bash tool environment and writes it to the
# task directory for dispatched workers.
#
# Claude Code provides session_id in the SessionStart hook's stdin JSON but does
# not export it as an environment variable. This script bridges the gap by:
#   1. Writing it to $CLAUDE_ENV_FILE so subsequent Bash tool calls can read it
#   2. Writing it to $BASECAMP_TASK_DIR/session_id so the orchestrator can
#      correlate workers to their observer transcripts

SESSION_ID=$(jq -r '.session_id // empty')

if [ -z "$SESSION_ID" ]; then
  exit 0
fi

# Reject session IDs with unsafe characters — only allow alphanumerics, hyphens, underscores
if ! echo "$SESSION_ID" | grep -qE '^[a-zA-Z0-9_-]+$'; then
  exit 1
fi

# Persist for Bash tool access
if [ -n "$CLAUDE_ENV_FILE" ]; then
  printf 'export CLAUDE_SESSION_ID=%s\n' "'$SESSION_ID'" >> "$CLAUDE_ENV_FILE"
fi

# Create and export task dispatch directory for this session
TASKS_DIR="/tmp/claude-workspace/tasks/$SESSION_ID"
mkdir -p "$TASKS_DIR"
if [ -n "$CLAUDE_ENV_FILE" ]; then
  printf 'export BASECAMP_TASKS_DIR=%s\n' "'$TASKS_DIR'" >> "$CLAUDE_ENV_FILE"
fi

# Write to task dir if this is a dispatched worker
if [ -n "$BASECAMP_TASK_DIR" ]; then
  echo "$SESSION_ID" > "$BASECAMP_TASK_DIR/session_id"
fi
