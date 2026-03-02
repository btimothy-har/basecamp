#!/bin/bash

json_input=$(cat)
tool_name=$(echo "$json_input" | jq -r '.tool_name')

command=$(echo "$json_input" | jq -r '.tool_input.command')

# Check if command starts with "git"
if [[ "$command" =~ ^git( |$) ]]; then
    # Check GPG unlock
    echo 'GPG Card Ok' | gpg --pinentry-mode error --clearsign >/dev/null 2>&1 || {
      # GPG is locked - output JSON to stop execution
      json_output=$(jq -n \
        --arg hookEventName "PreToolUse" \
        --arg permissionDecision "deny" \
        --arg permissionDecisionReason "User needs to unlock GPG card for git operations." \
        '{
          hookSpecificOutput: {
            hookEventName: $hookEventName,
            permissionDecision: $permissionDecision,
            permissionDecisionReason: $permissionDecisionReason
          }
        }')
      echo "$json_output"
      exit 2
    }
fi

exit 0
