#!/bin/bash
# Injects project-specific context at session start from BASECAMP_CONTEXT_FILE env var

# Guard: require BASECAMP_CONTEXT_FILE env var (set by launch if project.context exists)
if [ -z "$BASECAMP_CONTEXT_FILE" ]; then
  exit 0
fi

if [ -f "$BASECAMP_CONTEXT_FILE" ]; then
  CONTENT=$(cat "$BASECAMP_CONTEXT_FILE")
  jq -n --arg ctx "$CONTENT" '{
    hookSpecificOutput: {
      hookEventName: "SessionStart",
      additionalContext: $ctx
    }
  }'
fi
