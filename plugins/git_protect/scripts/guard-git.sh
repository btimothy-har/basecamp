#!/bin/bash
# Guard against destructive git operations (PreToolUse hook).
#
# DENY:       git push --force/--delete, git clean -f
# NO OPINION: everything else — falls through to user's permission settings

CMD=$(cat | jq -r '.tool_input.command // empty')
[[ -z "$CMD" ]] && exit 0

deny() {
  jq -n --arg reason "$1" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $reason
    }
  }'
  exit 0
}

# DENY: force push (--force, --force-with-lease, -f, or combined like -uf)
if [[ "$CMD" =~ ^git[[:space:]]+push ]]; then
  if [[ "$CMD" =~ [[:space:]](--force|--force-with-lease)([[:space:]]|$) ]] || \
     [[ "$CMD" =~ [[:space:]]-[a-zA-Z]*f ]]; then
    deny "Force push is blocked — protects remote history."
  fi

  # DENY: delete remote ref (--delete flag or :ref colon-prefix syntax)
  if [[ "$CMD" =~ [[:space:]]--delete([[:space:]]|$) ]] || \
     [[ "$CMD" =~ [[:space:]]:[^[:space:]] ]]; then
    deny "Deleting remote refs is blocked."
  fi
fi

# DENY: git clean -f (permanently destroys untracked files, not in reflog)
if [[ "$CMD" =~ ^git[[:space:]]+clean ]] && \
   [[ "$CMD" =~ [[:space:]](-[a-zA-Z]*f|--force) ]]; then
  deny "git clean -f permanently deletes untracked files — not recoverable."
fi

exit 0
