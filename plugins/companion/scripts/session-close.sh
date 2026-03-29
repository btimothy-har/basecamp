#!/bin/bash
# Close task entry on session end (dispatch workers only)
if [ -n "$BASECAMP_TASK_NAME" ]; then
  basecamp task close 2>/dev/null || true
fi
