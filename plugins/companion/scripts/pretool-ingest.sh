#!/bin/bash
# PreToolUse hook: trigger observer ingest before task dispatch.
#
# Detects `task create --dispatch` in Bash tool input and backgrounds
# the observer pipeline so the worker has recall access to the parent
# session's context.

# Skip when observer is not configured
if [ "${BASECAMP_OBSERVER_ENABLED}" != "1" ]; then
    exit 0
fi

# Skip in reflect mode
if [ "${BASECAMP_REFLECT}" = "1" ]; then
    exit 0
fi

# Only act on Bash tool calls
INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')
if [ "$TOOL_NAME" != "Bash" ]; then
    exit 0
fi

# Only act on dispatch commands
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
if ! echo "$CMD" | grep -qE 'task create.*--dispatch'; then
    exit 0
fi

# Require transcript path (persisted by session-init.sh)
if [ -z "$BASECAMP_TRANSCRIPT_PATH" ] || [ -z "$CLAUDE_SESSION_ID" ]; then
    exit 0
fi

# Build the hook input JSON that observer ingest expects
HOOK_JSON=$(jq -n \
    --arg session_id "$CLAUDE_SESSION_ID" \
    --arg transcript_path "$BASECAMP_TRANSCRIPT_PATH" \
    --arg cwd "${BASECAMP_SESSION_CWD:-$PWD}" \
    '{session_id: $session_id, transcript_path: $transcript_path, cwd: $cwd}')

# Background: ingest + process (detached, non-blocking)
echo "$HOOK_JSON" | nohup observer ingest --process >/dev/null 2>&1 &

exit 0
