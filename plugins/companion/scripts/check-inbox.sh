#!/bin/bash
# Check inbox for inter-agent messages and inject as additionalContext.
# Usage: check-inbox.sh <mode>
#   all       — read *.msg and *.immediate (used by Stop hook, blocks stop if messages found)
#   immediate — read *.immediate only (used by PostToolUse hook)

INBOX="$BASECAMP_INBOX_DIR"
[ -d "$INBOX" ] || exit 0

MODE="${1:-all}"

if [ "$MODE" = "immediate" ]; then
  FILES=$(find "$INBOX" -maxdepth 1 -name '*.immediate' -type f 2>/dev/null | sort)
else
  FILES=$(find "$INBOX" -maxdepth 1 \( -name '*.msg' -o -name '*.immediate' \) -type f 2>/dev/null | sort)
fi

[ -z "$FILES" ] && exit 0

# Collect all messages
MESSAGES=""
while IFS= read -r f; do
  [ -f "$f" ] || continue
  CONTENT=$(cat "$f")
  rm -f "$f"
  if [ -n "$MESSAGES" ]; then
    MESSAGES="${MESSAGES}
---
${CONTENT}"
  else
    MESSAGES="$CONTENT"
  fi
done <<< "$FILES"

# Build hook output
if [ "$MODE" = "all" ]; then
  # Stop: block with message content in reason — forces Claude to continue and read
  jq -n --arg msgs "$MESSAGES" '{
    decision: "block",
    reason: ("Incoming messages from another agent:\n" + $msgs)
  }'
else
  # PostToolUse: inject as additionalContext
  jq -n --arg msgs "$MESSAGES" '{
    hookSpecificOutput: {
      hookEventName: "PostToolUse",
      additionalContext: ("Incoming messages from another agent:\n" + $msgs)
    }
  }'
fi
