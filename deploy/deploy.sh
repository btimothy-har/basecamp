#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_CONTEXT="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVICE_NAME="basecamp-docs"
SERVICE_UNIT="${SERVICE_NAME}.service"
SERVICE_UNIT_TARGET="$HOME/.config/systemd/user/${SERVICE_UNIT}"

export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

log() {
    printf '[%s] %s\n' "$SERVICE_NAME" "$*"
}

log "build basecamp-docs:latest from ${BUILD_CONTEXT}"
podman build -f "$SCRIPT_DIR/Dockerfile" -t basecamp-docs:latest "$BUILD_CONTEXT"

mkdir -p "$HOME/.config/systemd/user"
rm -f "$SERVICE_UNIT_TARGET"
install -m 0644 "$SCRIPT_DIR/$SERVICE_UNIT" "$SERVICE_UNIT_TARGET"

log "systemctl daemon-reload"
systemctl --user daemon-reload

log "enable ${SERVICE_UNIT}"
systemctl --user enable "$SERVICE_NAME"

log "restart ${SERVICE_NAME}"
systemctl --user restart "$SERVICE_NAME"

log "verify ${SERVICE_NAME} is active"
if ! systemctl --user is-active --quiet "$SERVICE_NAME"; then
    echo "error: ${SERVICE_NAME} failed to become active" >&2
    exit 1
fi

log "deploy complete"
