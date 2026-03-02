#!/bin/bash
# Auto-approve mkdir when target directories already exist (PreToolUse hook).
#
# ALLOW:      mkdir where all target paths already exist (idempotent no-op)
# NO OPINION: everything else — falls through to user's permission settings

CMD=$(cat | jq -r '.tool_input.command // empty')
[[ -z "$CMD" ]] && exit 0

# Only act on simple mkdir commands (no chaining or substitution)
[[ "$CMD" =~ ^mkdir[[:space:]] ]] || exit 0
[[ "$CMD" == *";"* || "$CMD" == *"|"* || "$CMD" == *"&&"* || "$CMD" == *"||"* ]] && exit 0
[[ "$CMD" == *'$('* || "$CMD" == *'`'* || "$CMD" == *"<"* || "$CMD" == *">"* ]] && exit 0

# Split into words (safe, no eval)
read -r -a args <<< "$CMD"

# Extract paths (skip "mkdir" and flags)
paths=()
for arg in "${args[@]:1}"; do
  [[ "$arg" =~ ^- ]] && continue
  paths+=("$arg")
done

[[ ${#paths[@]} -eq 0 ]] && exit 0

# All paths must already exist (expand ~ without eval)
for p in "${paths[@]}"; do
  case "$p" in
    "~/"*) expanded="${HOME}/${p#"~/"}" ;;
    "~")   expanded="$HOME" ;;
    *)     expanded="$p" ;;
  esac
  [[ -d "$expanded" ]] || exit 0
done

jq -n '{
  hookSpecificOutput: {
    hookEventName: "PreToolUse",
    permissionDecision: "allow",
    permissionDecisionReason: "mkdir target(s) already exist"
  }
}'
