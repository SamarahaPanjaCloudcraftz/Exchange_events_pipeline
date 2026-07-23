#!/usr/bin/env bash
# Deliberate, gated redeploy: pull -> install -> test -> sync units -> migrate
# -> restart -> verify. One-stop-shop: any change anywhere in the repo -- app
# code, config, or a systemd unit file itself -- gets reflected on the server
# through this one script; nothing here should ever need a separate manual
# step for a routine change.
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
#   INSTALL_DIR=<current directory>      -- used only to path-substitute
#                                            deploy/systemd/* the same way
#                                            bootstrap_server.sh does, when
#                                            syncing changed unit files
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
INSTALL_DIR="${INSTALL_DIR:-$(pwd)}"
VENV_DIR="${VENV_DIR:-.venv}"
SERVICE_NAME="${SERVICE_NAME:-exchange-events-web}"
_env_port="$(grep -oP '^EXCHANGE_EVENTS_PORT=\K.*' .env 2>/dev/null || true)"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:${_env_port:-8080}/api/v1/exchanges}"
STATE_FILE="${STATE_FILE:-.last_good_deploy}"
PIP="${VENV_DIR}/bin/pip"
PY="${VENV_DIR}/bin/python"

log() { echo "[redeploy] $*"; }

# Bash reads this file into memory before running it -- `git checkout` below
# changes the file on disk, but the *currently executing* process keeps
# running the version it started with (verified directly: a script that
# checks out a new version of itself mid-run still executes its old body).
# So a fix to redeploy.sh's own logic could never take effect through
# redeploy.sh alone, and since a failed run reverts to the previous commit,
# it would fail identically forever. Fixed by re-exec'ing this same script
# immediately after checkout, via a stage marker so the second pass skips
# fetch/checkout (already done) and picks up install/test/restart using
# whatever this file now says on disk.
if [[ -z "${_REDEPLOY_STAGE2:-}" ]]; then
    previous_sha="$(git rev-parse HEAD)"

    log "fetching..."
    git fetch --quiet origin

    target_sha="$(git rev-parse "${REF}")"
    if [[ "${target_sha}" == "${previous_sha}" ]]; then
        log "already at ${target_sha:0:12} -- nothing to deploy."
        exit 0
    fi

    log "checking out ${REF} (${target_sha:0:12})"
    git checkout --quiet "${target_sha}"

    log "re-executing (picking up any change to redeploy.sh itself)..."
    exec env _REDEPLOY_STAGE2=1 _REDEPLOY_PREVIOUS_SHA="${previous_sha}" \
        "${BASH_SOURCE[0]}" "${REF}"
fi

previous_sha="${_REDEPLOY_PREVIOUS_SHA}"
target_sha="$(git rev-parse HEAD)"

revert_to_previous() {
    log "reverting working tree to previous known-good commit ${previous_sha}"
    git checkout --quiet "${previous_sha}"
}

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

# config/loader.py::load_config() defaults to reading .env from the CURRENT
# DIRECTORY -- which is exactly where the real, production .env lives when
# this script runs. Without this, every test that calls load_config() (i.e.
# nearly all of them) would silently pick up real secrets/paths, including
# EXCHANGE_EVENTS_SQLITE_PATH pointing at the REAL production database --
# discovered directly: a reproduction showed a test reporting stale state
# ("0 new alerts" instead of "1") because a prior run had already written
# that exact alert into the real, shared database. Tests must never be able
# to touch it. Hidden for the gate below, restored immediately after
# (success or failure) and again via EXIT trap as a safety net.
_env_hidden=0
if [[ -f .env ]]; then
    mv .env .env.redeploy_hidden
    _env_hidden=1
fi
restore_env() {
    if [[ "${_env_hidden}" -eq 1 && -f .env.redeploy_hidden ]]; then
        mv .env.redeploy_hidden .env
        _env_hidden=0
    fi
}
trap restore_env EXIT

log "running test suite (offline unit + integration + e2e)..."
if ! "${PY}" -m pytest -q; then
    log "FAILED: tests did not pass on ${target_sha:0:12}. Reverting, NOT restarting the live service."
    restore_env
    revert_to_previous
    "${PIP}" install --quiet --no-deps -e . >/dev/null 2>&1 || true
    exit 1
fi

log "running lint + type-check..."
if ! "${VENV_DIR}/bin/ruff" check src tests || ! "${VENV_DIR}/bin/mypy" src/exchange_events; then
    log "FAILED: ruff/mypy did not pass on ${target_sha:0:12}. Reverting, NOT restarting the live service."
    restore_env
    revert_to_previous
    "${PIP}" install --quiet --no-deps -e . >/dev/null 2>&1 || true
    exit 1
fi

restore_env

# One-stop-shop: a change anywhere in the repo -- code, config, or a systemd
# unit itself -- should be reflected on the server through this one script,
# not require a separate manual step. Re-render each unit under
# deploy/systemd/ with the same path substitution bootstrap_server.sh uses,
# and only touch /etc/systemd/system/ for ones that actually changed.
_units_changed=0
if [[ "${EUID}" -eq 0 ]]; then
    for unit in deploy/systemd/*; do
        _name="$(basename "${unit}")"
        if [[ "${INSTALL_DIR}" != "/opt/exchange-events" ]]; then
            _rendered="$(sed "s#/opt/exchange-events#${INSTALL_DIR}#g" "${unit}")"
        else
            _rendered="$(cat "${unit}")"
        fi
        if [[ ! -f "/etc/systemd/system/${_name}" ]] || \
           ! diff -q <(printf '%s' "${_rendered}") "/etc/systemd/system/${_name}" >/dev/null 2>&1; then
            log "systemd unit changed: ${_name} -- installing"
            printf '%s\n' "${_rendered}" > "/etc/systemd/system/${_name}"
            _units_changed=1
        fi
    done
    if [[ "${_units_changed}" -eq 1 ]]; then
        log "reloading systemd and restarting affected timers..."
        systemctl daemon-reload
        systemctl restart exchange-events-ingest.timer exchange-events-alert.timer 2>/dev/null || true
    fi
else
    log "WARNING: not running as root -- skipping systemd unit sync (can't write /etc/systemd/system/)."
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
