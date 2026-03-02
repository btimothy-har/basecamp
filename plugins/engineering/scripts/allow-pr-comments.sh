#!/bin/bash
# Skill-scoped PreToolUse hook: allow gh pr comment/review and gh api
# Active only when the pr-comments skill is loaded.
# Returns permissionDecision: "allow" to bypass permission deny rules.

set -euo pipefail

CMD=$(cat | jq -r '.tool_input.command // empty')

if [[ "$CMD" =~ ^gh[[:space:]]+pr[[:space:]]+(comment|review) ]] || \
   [[ "$CMD" =~ ^gh[[:space:]]+api[[:space:]]+repos/.+/pulls/.+/(comments|reviews) ]]; then
  jq -n '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "allow",
      permissionDecisionReason: "Allowed by pr-comments skill"
    }
  }'
fi

exit 0
