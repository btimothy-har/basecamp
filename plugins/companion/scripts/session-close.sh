#!/bin/bash
# Close worker entry on session end (dispatch workers only)
if [ -n "$BASECAMP_WORKER_NAME" ]; then
  basecamp worker close 2>/dev/null || true
fi
