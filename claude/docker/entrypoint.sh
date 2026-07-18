#!/usr/bin/env bash
# Print a short orientation banner, then hand over to an interactive shell.
set -euo pipefail

cat <<'BANNER'
──────────────────────────────────────────────────────────────────────
 basecamp × Claude Code — isolated validation sandbox
──────────────────────────────────────────────────────────────────────
Everything here writes to THIS container's $HOME. Your host's basecamp
database and Claude Code transcripts are untouched.

  1. Run a session (the plugin under test auto-loads):
         claude

  2. Inspect what the hub daemon recorded:
         bc-inspect

Locations (all inside the container):
  hub DB       ~/.pi/basecamp/claude/daemon.db
  transcripts  ~/.claude/projects/
  hook log     ~/.pi/basecamp/claude/hooks.log   (fail-open hook errors)
BANNER

echo "  plugin       ${BASECAMP_PLUGIN_DIR}"
echo

if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
	echo "ANTHROPIC_API_KEY     : set ✓"
else
	echo "ANTHROPIC_API_KEY     : NOT set ✗  — re-run the container with -e ANTHROPIC_API_KEY"
fi
# The base URL is an endpoint, not a secret, so show it; the custom headers may
# carry credentials, so only report whether they're present.
echo "ANTHROPIC_BASE_URL    : ${ANTHROPIC_BASE_URL:-<unset — direct api.anthropic.com>}"
echo "ANTHROPIC_CUSTOM_HEADERS: $([ -n "${ANTHROPIC_CUSTOM_HEADERS:-}" ] && echo 'set ✓' || echo '<unset>')"
echo "claude                : $(command claude --version 2>/dev/null || echo unavailable)"
echo "──────────────────────────────────────────────────────────────────────"

# Interactive shell; sources ~/.bashrc so the `claude` plugin alias is active.
exec bash
