#!/bin/bash

json_input=$(cat)
tool_name=$(echo "$json_input" | jq -r '.tool_name')

command=$(echo "$json_input" | jq -r '.tool_input.command')

# Check if command starts with "git"
if [[ "$command" =~ ^git( |$) ]]; then
    # Refresh GPG agent's TTY reference (fixes stale TTY in tmux)
    gpg-connect-agent updatestartuptty /bye >/dev/null 2>&1

    # Check GPG card is present and responsive
    gpg --card-status >/dev/null 2>&1 || {
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
