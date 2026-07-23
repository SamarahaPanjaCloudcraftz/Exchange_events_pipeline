#!/usr/bin/env bash
# Deliberate, gated redeploy: pull -> install -> test -> migrate -> restart -> verify.
#
# Cron jobs (`exchange-events ingest` / `alert`) never run this -- they just
# execute whatever is already installed. This script is the only thing that
# changes what "already installed" means, and it never leaves the working tree
# on an untested commit: on any failure it reverts to the last known-good SHA
# before exiting, so a failed redeploy can never smuggle bad code onto disk for
# the next cron tick to pick up.
#
# Usage: scripts/redeploy.sh [git-ref]   (default ref: origin/main)
#
# Configure via env vars (defaults shown):
#   VENV_DIR=.venv
#   SERVICE_NAME=exchange-events-web     # systemd unit for the gunicorn service
#   HEALTH_URL=http://127.0.0.1:${EXCHANGE_EVENTS_PORT}/api/v1/exchanges
#                                         -- port read from .env (same single
#                                            source of truth as the systemd
#                                            unit); override HEALTH_URL
#                                            directly only if genuinely needed
#   STATE_FILE=.last_good_deploy

set -euo pipefail

REF="${1:-origin/main}"
VENV_DIR="${VENV_DIR:-.venv}"
SERVICE_NAME="${SERVICE_NAME:-exchange-events-web}"
_env_port="$(grep -oP '^EXCHANGE_EVENTS_PORT=\K.*' .env 2>/dev/null || true)"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:${_env_port:-8080}/api/v1/exchanges}"
STATE_FILE="${STATE_FILE:-.last_good_deploy}"
PIP="${VENV_DIR}/bin/pip"
PY="${VENV_DIR}/bin/python"

log() { echo "[redeploy] $*"; }

previous_sha="$(git rev-parse HEAD)"

revert_to_previous() {
    log "reverting working tree to previous known-good commit ${previous_sha}"
    git checkout --quiet "${previous_sha}"
}

log "fetching..."
git fetch --quiet origin

target_sha="$(git rev-parse "${REF}")"
if [[ "${target_sha}" == "${previous_sha}" ]]; then
    log "already at ${target_sha:0:12} -- nothing to deploy."
    exit 0
fi

log "checking out ${REF} (${target_sha:0:12})"
git checkout --quiet "${target_sha}"

log "installing locked dependencies..."
if ! "${PIP}" install --quiet -r requirements.lock.txt; then
    log "FAILED: dependency install. Reverting."
    revert_to_previous
    exit 1
fi
"${PIP}" install --quiet --no-deps -e .

log "installing test tooling (pytest/ruff/mypy) needed for the gate below..."
if ! "${PIP}" install --quiet -e ".[dev]"; then
    log "FAILED: test tooling install. Reverting."
    revert_to_previous
    exit 1
fi

log "running test suite (offline unit + integration + e2e)..."
if ! "${PY}" -m pytest -q; then
    log "FAILED: tests did not pass on ${target_sha:0:12}. Reverting, NOT restarting the live service."
    revert_to_previous
    "${PIP}" install --quiet --no-deps -e . >/dev/null 2>&1 || true
    exit 1
fi

log "running lint + type-check..."
if ! "${VENV_DIR}/bin/ruff" check src tests || ! "${VENV_DIR}/bin/mypy" src/exchange_events; then
    log "FAILED: ruff/mypy did not pass on ${target_sha:0:12}. Reverting, NOT restarting the live service."
    revert_to_previous
    "${PIP}" install --quiet --no-deps -e . >/dev/null 2>&1 || true
    exit 1
fi

log "applying schema (idempotent -- safe every deploy)..."
"${VENV_DIR}/bin/exchange-events" init-db

log "restarting ${SERVICE_NAME}..."
systemctl restart "${SERVICE_NAME}"

log "waiting for health check..."
sleep 2
if ! curl -sf -o /dev/null "${HEALTH_URL}"; then
    log "FAILED: health check did not return 200 after restart. Rolling back to ${previous_sha:0:12}."
    git checkout --quiet "${previous_sha}"
    "${PIP}" install --quiet -r requirements.lock.txt
    "${PIP}" install --quiet --no-deps -e .
    "${VENV_DIR}/bin/exchange-events" init-db
    systemctl restart "${SERVICE_NAME}"
    exit 1
fi

echo "${target_sha}" > "${STATE_FILE}"
log "deploy of ${target_sha:0:12} succeeded and is now live."
