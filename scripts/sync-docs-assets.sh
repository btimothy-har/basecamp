#!/usr/bin/env bash
# Shared brand assets live with the code that owns them (the dashboard) and are
# copied into the docs source here so mkdocs can serve them — one source of truth.
# Run before any mkdocs build/serve (Makefile docs/docs-build, CI docs gate, deploy).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/src/basecamp/hub/dashboard/assets/favicon.svg"

if [[ ! -f "$SRC" ]]; then
    echo "sync-docs-assets: source favicon not found at $SRC" >&2
    exit 1
fi

mkdir -p "$ROOT/docs/assets" "$ROOT/docs/overrides/.icons"
cp "$SRC" "$ROOT/docs/assets/favicon.svg"
cp "$SRC" "$ROOT/docs/overrides/.icons/basecamp.svg"
