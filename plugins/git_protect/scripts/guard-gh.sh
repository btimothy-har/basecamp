#!/bin/bash
# Guard against destructive gh operations (PermissionRequest hook).
#
# Fires only when a permission dialog is about to appear.
# Skill-scoped hooks (pr create/edit, api, etc.) resolve at PreToolUse,
# so PermissionRequest never fires for those commands.
#
# ALLOW: read-only operations (view, list, diff, checks, status, clone, search, browse)
# DENY:  everything else — run from terminal if needed

CMD=$(cat | jq -r '.tool_input.command // empty')
[[ -z "$CMD" ]] && exit 0

# Only act on gh commands
[[ "$CMD" =~ ^gh[[:space:]] ]] || exit 0

allow() {
  jq -n '{
    hookSpecificOutput: {
      hookEventName: "PermissionRequest",
      decision: { behavior: "allow" }
    }
  }'
  exit 0
}

deny() {
  jq -n '{
    hookSpecificOutput: {
      hookEventName: "PermissionRequest",
      decision: { behavior: "deny" }
    }
  }'
  exit 0
}

# ALLOW: read-only operations
if [[ "$CMD" =~ ^gh[[:space:]]+(pr|issue|run)[[:space:]]+(view|list|diff|checks|status)([[:space:]]|$) ]] || \
   [[ "$CMD" =~ ^gh[[:space:]]+repo[[:space:]]+(view|list|clone|set-default)([[:space:]]|$) ]] || \
   [[ "$CMD" =~ ^gh[[:space:]]+run[[:space:]]+watch([[:space:]]|$) ]] || \
   [[ "$CMD" =~ ^gh[[:space:]]+search[[:space:]] ]] || \
   [[ "$CMD" =~ ^gh[[:space:]]+browse([[:space:]]|$) ]]; then
  allow
fi

# DENY: all other gh commands
deny
