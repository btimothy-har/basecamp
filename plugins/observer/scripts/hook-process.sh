#!/bin/bash
# Hook handler for PreCompact and SessionEnd events.
# Synchronous: ingest (parse + group)
# Async: fire background process (refine + extract + embed)

# Skip in reflect mode
if [ "${BASECAMP_REFLECT}" = "1" ]; then
    exit 0
fi

# Read hook input and extract session_id
INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin)['session_id'])")

# Synchronous: ingest new events
echo "$INPUT" | observer ingest 2>/dev/null || true

# Background: refine + extract + embed (detached, non-blocking)
nohup observer process "$SESSION_ID" >/dev/null 2>&1 &

exit 0
