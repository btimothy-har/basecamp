#!/bin/bash
# Check inbox for inter-agent messages and inject as additionalContext.
# Usage: check-inbox.sh <mode>
#   all       — read *.msg and *.immediate (used by Stop hook)
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
for f in $FILES; do
  CONTENT=$(cat "$f")
  rm -f "$f"
  if [ -n "$MESSAGES" ]; then
    MESSAGES="${MESSAGES}
---
${CONTENT}"
  else
    MESSAGES="$CONTENT"
  fi
done

# Escape for JSON
ESCAPED=$(printf '%s' "$MESSAGES" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read()))')

printf '{"additionalContext": %s}' "$ESCAPED"
