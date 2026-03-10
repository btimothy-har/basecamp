#!/bin/bash
# Agent-scoped PreToolUse hook: allow gh issue create/edit/close
# Active only when the issue-worker agent is running.
# Returns permissionDecision: "allow" to bypass permission deny rules.

set -euo pipefail

CMD=$(cat | jq -r '.tool_input.command // empty')

if [[ "$CMD" =~ ^gh[[:space:]]+issue[[:space:]]+(create|edit|close) ]]; then
  jq -n '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "allow",
      permissionDecisionReason: "Allowed by issue-worker agent"
    }
  }'
fi

exit 0
