#!/bin/bash
# Register the current Claude Code session with the observer daemon.
# Reads session metadata from stdin (JSON) and pipes to `observer register`.
# Failure is silent — registration should never block session start.

cat | observer register 2>/dev/null || true
