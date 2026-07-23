#!/usr/bin/env bash
# First-time server setup. Run ONCE, as root, from inside a checkout of this
# repo already cloned to its final location (default: /opt/exchange-events --
# clone there directly, cd in, then `./scripts/bootstrap_server.sh`).
#
# Runs everything as root, matching the existing HARCJ dashboard's own model
# on this host (its Streamlit + scheduler processes also run as root) -- a
# deliberate choice for this specific server, not a general recommendation.
# There is no dedicated low-privilege service user here; see
# docs/REAL_DEPLOYMENT_LOG.md for the isolation trade-off this accepts.
#
# After this, scripts/redeploy.sh is what updates code on every subsequent
# deploy -- this script never needs to run again unless setting up a second
# server.
#
# What it does:
#   1. Creates a persistent data/ dir (for the SQLite file) and a log dir.
#   2. Builds a venv here and installs from requirements.lock.txt.
#   3. Copies the systemd units from deploy/systemd/ into /etc/systemd/system/
#      (substituting the install path if it differs from /opt/exchange-events).
#   4. Scaffolds .env from .env.example if it doesn't exist yet, pre-filling
#      only the one non-secret value this script already knows
#      (EXCHANGE_EVENTS_SQLITE_PATH) -- every actual secret still needs to be
#      filled in by hand afterwards.
#   5. Runs init-db, then enables + starts all three units.
#
# Configure via env vars (defaults shown):
#   INSTALL_DIR=/opt/exchange-events
#   PYTHON=python3   -- must be >=3.11; point this at whatever real 3.11+
#                       interpreter is available (system python3 is often
#                       too old -- verify with `PYTHON --version` first).

set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    echo "must be run as root (this box runs everything as root -- see script header)" >&2
    exit 1
fi

INSTALL_DIR="${INSTALL_DIR:-/opt/exchange-events}"
PYTHON="${PYTHON:-python3}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log() { echo "[bootstrap] $*"; }

if [[ ! -f "${REPO_DIR}/wsgi.py" || ! -f "${REPO_DIR}/pyproject.toml" ]]; then
    echo "error: ${REPO_DIR} doesn't look like the exchange-events checkout" >&2
    exit 1
fi

if [[ "${REPO_DIR}" != "${INSTALL_DIR}" ]]; then
    log "WARNING: running from ${REPO_DIR} but INSTALL_DIR is ${INSTALL_DIR}."
    log "The systemd units hardcode ${INSTALL_DIR} as WorkingDirectory -- either"
    log "re-clone directly into ${INSTALL_DIR}, or re-run with INSTALL_DIR=${REPO_DIR}."
fi

log "creating persistent data + log directories..."
mkdir -p "${INSTALL_DIR}/data" /var/log/exchange-events
chmod 700 "${INSTALL_DIR}/data" /var/log/exchange-events

log "building venv at ${INSTALL_DIR}/.venv using ${PYTHON} ($("${PYTHON}" --version))..."
"${PYTHON}" -m venv "${INSTALL_DIR}/.venv"
"${INSTALL_DIR}/.venv/bin/pip" install --quiet --upgrade pip
"${INSTALL_DIR}/.venv/bin/pip" install --quiet -r "${REPO_DIR}/requirements.lock.txt"
"${INSTALL_DIR}/.venv/bin/pip" install --quiet --no-deps -e "${REPO_DIR}"

if [[ ! -f "${INSTALL_DIR}/.env" ]]; then
    log "scaffolding ${INSTALL_DIR}/.env from .env.example (fill in real secrets after)..."
    cp "${REPO_DIR}/.env.example" "${INSTALL_DIR}/.env"
    echo "EXCHANGE_EVENTS_SQLITE_PATH=${INSTALL_DIR}/data/exchange_events.db" >> "${INSTALL_DIR}/.env"
    chmod 600 "${INSTALL_DIR}/.env"
else
    log "${INSTALL_DIR}/.env already exists -- leaving it untouched."
fi

log "installing systemd units..."
for unit in "${REPO_DIR}"/deploy/systemd/*; do
    name="$(basename "${unit}")"
    if [[ "${INSTALL_DIR}" != "/opt/exchange-events" ]]; then
        sed "s#/opt/exchange-events#${INSTALL_DIR}#g" "${unit}" > "/etc/systemd/system/${name}"
    else
        cp "${unit}" "/etc/systemd/system/${name}"
    fi
done
systemctl daemon-reload

log "applying schema..."
(cd "${INSTALL_DIR}" && "${INSTALL_DIR}/.venv/bin/exchange-events" init-db)

log "enabling + starting units..."
systemctl enable --now exchange-events-web.service
systemctl enable --now exchange-events-ingest.timer
systemctl enable --now exchange-events-alert.timer

cat <<EOF

[bootstrap] Done. Remaining manual steps:
  1. Edit ${INSTALL_DIR}/.env and fill in real secrets (FRED_API_KEY, SMTP_*,
     TEAMS_WEBHOOK_URL, ALERT_RECIPIENT_EMAIL, CME_API_ID/SECRET, etc.) --
     see .env.example for the full list.
  2. systemctl restart exchange-events-web   (to pick up the secrets)
  3. curl http://127.0.0.1:8502/api/v1/exchanges  (should return 200)
  4. From here on, scripts/redeploy.sh handles every future code update.
EOF
