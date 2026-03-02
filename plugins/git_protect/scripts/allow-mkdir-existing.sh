#!/bin/bash
# Auto-approve mkdir when target directories already exist (PreToolUse hook).
#
# ALLOW:      mkdir where all target paths already exist (idempotent no-op)
# NO OPINION: everything else — falls through to user's permission settings

CMD=$(cat | jq -r '.tool_input.command // empty')
[[ -z "$CMD" ]] && exit 0

# Only act on simple mkdir commands (no chaining)
[[ "$CMD" =~ ^mkdir[[:space:]] ]] || exit 0
[[ "$CMD" == *";"* || "$CMD" == *"|"* || "$CMD" == *"&&"* ]] && exit 0

# Extract paths (skip flags)
paths=()
eval set -- $CMD 2>/dev/null || exit 0
shift  # drop "mkdir"
for arg in "$@"; do
  [[ "$arg" =~ ^- ]] && continue
  paths+=("$arg")
done

[[ ${#paths[@]} -eq 0 ]] && exit 0

# All paths must already exist
for p in "${paths[@]}"; do
  expanded=$(eval echo "$p" 2>/dev/null) || exit 0
  [[ -d "$expanded" ]] || exit 0
done

jq -n '{
  hookSpecificOutput: {
    hookEventName: "PreToolUse",
    permissionDecision: "allow",
    permissionDecisionReason: "mkdir target(s) already exist"
  }
}'
