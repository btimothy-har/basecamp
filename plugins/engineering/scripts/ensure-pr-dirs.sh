#!/usr/bin/env bash
# Create PR workflow directories expected by pull-request and pr-comments skills.
# Runs as a SessionStart hook; BASECAMP_REPO is set by launch.py.

set -euo pipefail

SCRATCH="/tmp/claude-workspace/${BASECAMP_REPO:?BASECAMP_REPO not set}"

mkdir -p "$SCRATCH/pull_requests"
mkdir -p "$SCRATCH/pr-comments"
