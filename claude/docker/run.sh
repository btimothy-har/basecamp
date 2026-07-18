#!/usr/bin/env bash
# Build and enter the basecamp × Claude Code validation sandbox.
#
# Engine-agnostic: defaults to podman (docker works too via ENGINE=docker). The
# host ANTHROPIC_API_KEY is forwarded into the container at runtime and is never
# baked into the image.
#
#   ./claude/docker/run.sh                 # build + interactive shell (podman)
#   ENGINE=docker ./claude/docker/run.sh   # same, with docker
#   IMAGE=my-tag ./claude/docker/run.sh    # override the image tag
#
# The container is --rm (throwaway): each run starts from an empty DB, which is
# the isolation guarantee. Drop --rm below if you want data to persist.
set -euo pipefail

ENGINE="${ENGINE:-podman}"
IMAGE="${IMAGE:-basecamp-claude-sandbox}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if ! command -v "${ENGINE}" >/dev/null 2>&1; then
	echo "error: container engine '${ENGINE}' not found (set ENGINE=docker|podman)" >&2
	exit 1
fi

echo "==> Building ${IMAGE} with ${ENGINE} (context: ${REPO_ROOT})"
"${ENGINE}" build -f "${REPO_ROOT}/claude/docker/Dockerfile" -t "${IMAGE}" "${REPO_ROOT}"

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
	echo "warning: ANTHROPIC_API_KEY is not set in your shell — 'claude' won't authenticate inside." >&2
fi

# Forward the full Anthropic auth/routing triplet so a gateway/proxy setup works
# inside the container (base URL + custom headers), not just a direct API key.
# CLAUDE_CODE_* vars from an outer session are deliberately NOT forwarded.
echo "==> Entering ${IMAGE} (transcripts + hub DB stay inside the container)"
exec "${ENGINE}" run --rm -it \
	-e ANTHROPIC_API_KEY \
	-e ANTHROPIC_BASE_URL \
	-e ANTHROPIC_CUSTOM_HEADERS \
	"${IMAGE}"
