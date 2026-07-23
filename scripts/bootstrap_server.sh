#!/usr/bin/env bash
# First-time server setup. Run ONCE, as root, from inside a checkout of this
# repo already cloned to its final location (default: /opt/exchange-events --
# clone there directly, cd in, then `sudo ./scripts/bootstrap_server.sh`).
#
# After this, scripts/redeploy.sh is what updates code on every subsequent
# deploy -- this script never needs to run again unless setting up a second
# server.
#
# What it does:
#   1. Creates a dedicated system user/group (`exchange-events`) -- the web
#      service and cron jobs run as this user, never as root, and never as
#      whatever user/account runs the other system on this host.
#   2. Creates a persistent data/ dir (for the SQLite file) and a log dir,
#      owned by that user.
#   3. Builds a venv here and installs from requirements.lock.txt.
#   4. Copies the systemd units from deploy/systemd/ into /etc/systemd/system/
#      (substituting the install path if it differs from /opt/exchange-events).
#   5. Scaffolds .env from .env.example if it doesn't exist yet, pre-filling
#      only the one non-secret value this script already knows
#      (EXCHANGE_EVENTS_SQLITE_PATH) -- every actual secret still needs to be
#      filled in by hand afterwards.
#   6. Runs init-db as the service user (so the resulting file is owned
#      correctly), then enables + starts all three units.
#
# Configure via env vars (defaults shown):
#   INSTALL_DIR=/opt/exchange-events
#   SERVICE_USER=exchange-events
#   PYTHON=python3

set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    echo "must be run as root (sudo ./scripts/bootstrap_server.sh)" >&2
    exit 1
fi

INSTALL_DIR="${INSTALL_DIR:-/opt/exchange-events}"
SERVICE_USER="${SERVICE_USER:-exchange-events}"
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

log "creating system user/group '${SERVICE_USER}' (if not already present)..."
if ! id -u "${SERVICE_USER}" >/dev/null 2>&1; then
    useradd --system --no-create-home --shell /usr/sbin/nologin "${SERVICE_USER}"
fi

log "creating persistent data + log directories..."
mkdir -p "${INSTALL_DIR}/data" /var/log/exchange-events
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}/data" /var/log/exchange-events
chmod 750 "${INSTALL_DIR}/data" /var/log/exchange-events

log "building venv at ${INSTALL_DIR}/.venv..."
"${PYTHON}" -m venv "${INSTALL_DIR}/.venv"
"${INSTALL_DIR}/.venv/bin/pip" install --quiet --upgrade pip
"${INSTALL_DIR}/.venv/bin/pip" install --quiet -r "${REPO_DIR}/requirements.lock.txt"
"${INSTALL_DIR}/.venv/bin/pip" install --quiet --no-deps -e "${REPO_DIR}"

if [[ ! -f "${INSTALL_DIR}/.env" ]]; then
    log "scaffolding ${INSTALL_DIR}/.env from .env.example (fill in real secrets after)..."
    cp "${REPO_DIR}/.env.example" "${INSTALL_DIR}/.env"
    echo "EXCHANGE_EVENTS_SQLITE_PATH=${INSTALL_DIR}/data/exchange_events.db" >> "${INSTALL_DIR}/.env"
    chown "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}/.env"
    chmod 640 "${INSTALL_DIR}/.env"
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

log "applying schema as ${SERVICE_USER} (creates the SQLite file with correct ownership)..."
(cd "${INSTALL_DIR}" && sudo -u "${SERVICE_USER}" "${INSTALL_DIR}/.venv/bin/exchange-events" init-db)

log "enabling + starting units..."
systemctl enable --now exchange-events-web.service
systemctl enable --now exchange-events-ingest.timer
systemctl enable --now exchange-events-alert.timer

cat <<EOF

[bootstrap] Done. Remaining manual steps:
  1. Edit ${INSTALL_DIR}/.env and fill in real secrets (FRED_API_KEY, SMTP_*,
     TEAMS_WEBHOOK_URL, ALERT_RECIPIENT_EMAIL, CME_API_ID/SECRET, etc.) --
     see .env.example for the full list.
  2. sudo systemctl restart exchange-events-web   (to pick up the secrets)
  3. curl http://127.0.0.1:8080/api/v1/exchanges  (should return 200)
  4. From here on, scripts/redeploy.sh handles every future code update.
EOF
