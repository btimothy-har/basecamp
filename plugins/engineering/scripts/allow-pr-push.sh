#!/bin/bash
# Skill-scoped PreToolUse hook: allow gh pr create/edit
# Active only when the pull-request skill is loaded.
# Returns permissionDecision: "allow" to bypass permission deny rules.

set -euo pipefail

CMD=$(cat | jq -r '.tool_input.command // empty')

if [[ "$CMD" =~ ^gh[[:space:]]+pr[[:space:]]+(create|edit)([[:space:]]|$) ]]; then
  jq -n '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "allow",
      permissionDecisionReason: "Allowed by pull-request skill"
    }
  }'
fi

exit 0
