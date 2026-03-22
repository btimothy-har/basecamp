#!/bin/bash
# Hook handler for PreCompact and SessionEnd events.
# Backgrounds the full pipeline (ingest + process) so the hook
# returns immediately. Errors go to observer.log.

# Skip when observer is not configured
if [ "${BASECAMP_OBSERVER_ENABLED}" != "1" ]; then
    exit 0
fi

# Skip in reflect mode
if [ "${BASECAMP_REFLECT}" = "1" ]; then
    exit 0
fi

# Read hook input
INPUT=$(cat)

# Background: ingest + process (detached, non-blocking)
echo "$INPUT" | nohup observer ingest --process >/dev/null 2>&1 &

exit 0
