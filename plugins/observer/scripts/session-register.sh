#!/bin/bash
# Register the current Claude Code session with the observer daemon.
# Reads session metadata from stdin (JSON) and pipes to `observer register`.
# Failure is silent — registration should never block session start.
# Skip registration in reflect mode — reflect sessions aren't work sessions.

if [ "${BASECAMP_REFLECT}" = "1" ]; then
    exit 0
fi

cat | observer register 2>/dev/null || true
