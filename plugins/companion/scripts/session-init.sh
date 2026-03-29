#!/bin/bash
# Exposes CLAUDE_SESSION_ID to the Bash tool environment.
#
# Claude Code provides session_id in the SessionStart hook's stdin JSON but does
# not export it as an environment variable. This script bridges the gap by
# writing it to $CLAUDE_ENV_FILE so subsequent Bash tool calls can read it.

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
