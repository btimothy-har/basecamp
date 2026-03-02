#!/bin/bash
# PreToolUse hook: Remind to load skill based on file extension
# Non-blocking - just provides a reminder via systemMessage

set -euo pipefail

json_input=$(cat)
file_path=$(echo "$json_input" | jq -r '.tool_input.file_path // empty')

# Exit silently if no file path
if [[ -z "$file_path" ]]; then
  exit 0
fi

# Check extension and output reminder
case "$file_path" in
  *.py)
    cat <<'EOF'
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow",
    "additionalContext": "Load the python-development skill for Python best practices."
  }
}
EOF
    ;;
  *.sql)
    cat <<'EOF'
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow",
    "additionalContext": "Load the sql skill for SQL best practices."
  }
}
EOF
    ;;
  *)
    # No reminder needed
    exit 0
    ;;
esac
