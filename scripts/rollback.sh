#!/usr/bin/env bash
# Roll back to a specific commit (default: the last commit redeploy.sh verified
# as live, recorded in .last_good_deploy). Does NOT re-run the test suite --
# by definition this SHA already passed it during its own redeploy.
#
# Usage: scripts/rollback.sh [git-sha]

set -euo pipefail

VENV_DIR="${VENV_DIR:-.venv}"
SERVICE_NAME="${SERVICE_NAME:-exchange-events-web}"
_env_port="$(grep -oP '^EXCHANGE_EVENTS_PORT=\K.*' .env 2>/dev/null || true)"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:${_env_port:-8080}/api/v1/exchanges}"
STATE_FILE="${STATE_FILE:-.last_good_deploy}"
PIP="${VENV_DIR}/bin/pip"

log() { echo "[rollback] $*"; }

target_sha="${1:-}"
if [[ -z "${target_sha}" ]]; then
    if [[ ! -f "${STATE_FILE}" ]]; then
        log "no ${STATE_FILE} found and no SHA given -- nothing to roll back to."
        exit 1
    fi
    target_sha="$(cat "${STATE_FILE}")"
fi

log "rolling back to ${target_sha:0:12}"
git checkout --quiet "${target_sha}"
"${PIP}" install --quiet -r requirements.lock.txt
"${PIP}" install --quiet --no-deps -e .
"${VENV_DIR}/bin/exchange-events" init-db
systemctl restart "${SERVICE_NAME}"

sleep 2
if ! curl -sf -o /dev/null "${HEALTH_URL}"; then
    log "WARNING: health check still failing after rollback to ${target_sha:0:12} -- this needs a human."
    exit 1
fi

echo "${target_sha}" > "${STATE_FILE}"
log "rollback to ${target_sha:0:12} succeeded."
