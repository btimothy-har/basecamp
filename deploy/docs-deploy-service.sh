#!/usr/bin/env bash
set -euo pipefail

log() {
    printf '[deploy-service] %s\n' "$*"
}

write_ssh_private_key() {
    local normalized_key="$SSH_PRIVATE_KEY"

    normalized_key="${normalized_key//$'\r'/}"
    normalized_key="${normalized_key//\\r\\n/$'\n'}"
    normalized_key="${normalized_key//\\n/$'\n'}"

    printf '%s\n' "$normalized_key" > "$SSH_KEY_FILE"
    chmod 600 "$SSH_KEY_FILE"
}

validate_ssh_private_key() {
    if ssh-keygen -y -P "" -f "$SSH_KEY_FILE" >/dev/null 2>&1; then
        return
    fi

    cat >&2 <<'EOF'
error: SSH_PRIVATE_KEY could not be parsed as an SSH private key.
SSH_PRIVATE_KEY must contain an unencrypted private key, not a public key.
Verify the secret includes the BEGIN/END private key lines and uses real newlines; literal \n sequences are also normalized by this helper.
EOF
    exit 1
}

: "${DEPLOY_SERVICE:?Environment variable DEPLOY_SERVICE is required.}"
: "${SSH_HOST:?Environment variable SSH_HOST is required.}"
: "${SSH_USER:?Environment variable SSH_USER is required.}"
: "${SSH_PRIVATE_KEY:?Environment variable SSH_PRIVATE_KEY is required.}"

SSH_PORT="${SSH_PORT:-22}"
DEPLOY_REMOTE_ROOT="${DEPLOY_REMOTE_ROOT:-.local/share/basecamp}"

DEPLOY_DIR="deploy"
DOCS_DIR="docs"
MKDOCS_FILE="mkdocs.yml"
LOCAL_DEPLOY_SCRIPT="${DEPLOY_DIR}/deploy.sh"

if [[ ! -f "$LOCAL_DEPLOY_SCRIPT" ]]; then
    echo "error: required deploy script missing: ${LOCAL_DEPLOY_SCRIPT}" >&2
    exit 1
fi

if ! command -v rsync >/dev/null 2>&1; then
    echo "error: rsync is required but not available" >&2
    exit 1
fi

if ! command -v ssh >/dev/null 2>&1; then
    echo "error: ssh is required but not available" >&2
    exit 1
fi

if ! command -v ssh-keygen >/dev/null 2>&1; then
    echo "error: ssh-keygen is required but not available" >&2
    exit 1
fi

TMPDIR=$(mktemp -d)
SSH_KEY_FILE="${TMPDIR}/id_deploy_service"
KNOWN_HOSTS_FILE="${TMPDIR}/known_hosts"
trap 'rm -rf "$TMPDIR"' EXIT

write_ssh_private_key
validate_ssh_private_key

if [[ -n "${SSH_KNOWN_HOSTS:-}" ]]; then
    printf '%s\n' "$SSH_KNOWN_HOSTS" > "$KNOWN_HOSTS_FILE"
else
    ssh-keyscan -p "$SSH_PORT" -H "$SSH_HOST" > "$KNOWN_HOSTS_FILE"
fi

SSH_ARGS=(
    -i "$SSH_KEY_FILE"
    -p "$SSH_PORT"
    -o "UserKnownHostsFile=$KNOWN_HOSTS_FILE"
    -o "StrictHostKeyChecking=yes"
)

REMOTE_ROOT="${DEPLOY_REMOTE_ROOT}"
REMOTE_DEPLOY_DIR="${REMOTE_ROOT}/deploy"
REMOTE_DOCS_DIR="${REMOTE_ROOT}/docs"

log "Preparing ${SSH_USER}@${SSH_HOST}:${REMOTE_ROOT}"
ssh "${SSH_ARGS[@]}" "${SSH_USER}@${SSH_HOST}" bash -s -- "$REMOTE_ROOT" <<'REMOTE_SCRIPT'
set -euo pipefail
remote_root=${1:?remote root directory is required}
mkdir -p "$remote_root/deploy" "$remote_root/docs"
REMOTE_SCRIPT

log "Syncing ${DEPLOY_DIR} to ${SSH_USER}@${SSH_HOST}:${REMOTE_DEPLOY_DIR}"
rsync -az \
    --delete \
    --exclude 'data/' \
    --exclude 'env.local' \
    -e "ssh ${SSH_ARGS[*]}" \
    "${DEPLOY_DIR}/" \
    "${SSH_USER}@${SSH_HOST}:${REMOTE_DEPLOY_DIR}/"

log "Syncing ${DOCS_DIR} to ${SSH_USER}@${SSH_HOST}:${REMOTE_DOCS_DIR}"
rsync -az \
    --delete \
    --exclude 'data/' \
    --exclude 'env.local' \
    -e "ssh ${SSH_ARGS[*]}" \
    "${DOCS_DIR}/" \
    "${SSH_USER}@${SSH_HOST}:${REMOTE_DOCS_DIR}/"

log "Copying ${MKDOCS_FILE} to ${SSH_USER}@${SSH_HOST}:${REMOTE_ROOT}/${MKDOCS_FILE}"
rsync -az \
    -e "ssh ${SSH_ARGS[*]}" \
    "${MKDOCS_FILE}" \
    "${SSH_USER}@${SSH_HOST}:${REMOTE_ROOT}/${MKDOCS_FILE}"

log "Running remote deploy"
ssh "${SSH_ARGS[@]}" "${SSH_USER}@${SSH_HOST}" bash -s -- "$REMOTE_ROOT" "$DEPLOY_SERVICE" <<'REMOTE_SCRIPT'
set -euo pipefail
remote_root=${1:?remote root directory is required}
service_name=${2:?service name is required}
mkdir -p "$remote_root"
cd "$remote_root"
chmod +x ./deploy/deploy.sh
DEPLOY_SERVICE="$service_name" ./deploy/deploy.sh
REMOTE_SCRIPT

log "Deploy complete"
