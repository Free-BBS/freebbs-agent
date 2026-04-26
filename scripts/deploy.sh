#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_DIR="${DEPLOY_DIR:-/data/www/freebbs-agent}"
ENV_FILE="${FREEBBS_AGENT_ENV_FILE:-/etc/free-bbs/freebbs-agent.env}"
SERVICE_NAME="${AGENT_SERVICE_NAME:-free-bbs-agent}"
HEALTHCHECK_URL="${HEALTHCHECK_URL:-http://127.0.0.1:5001/health}"
HEALTHCHECK_RETRIES="${HEALTHCHECK_RETRIES:-15}"
HEALTHCHECK_DELAY_SECONDS="${HEALTHCHECK_DELAY_SECONDS:-2}"

mkdir -p "$DEPLOY_DIR"

echo "[deploy] syncing project to $DEPLOY_DIR"
rsync -a --delete \
  --exclude ".git" \
  --exclude ".venv" \
  --exclude "__pycache__" \
  "$ROOT_DIR"/ "$DEPLOY_DIR"/

cd "$DEPLOY_DIR"

echo "[deploy] creating virtual environment"
python3 -m venv .venv

echo "[deploy] installing dependencies"
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

if [[ ! -f "$ENV_FILE" ]]; then
  echo "[deploy] missing env file: $ENV_FILE" >&2
  exit 1
fi

echo "[deploy] restarting service"
sudo systemctl restart "$SERVICE_NAME"
sudo systemctl --no-pager --full status "$SERVICE_NAME"

echo "[deploy] checking health: $HEALTHCHECK_URL"
for ((attempt = 1; attempt <= HEALTHCHECK_RETRIES; attempt++)); do
  if curl --fail --silent --show-error "$HEALTHCHECK_URL" >/dev/null; then
    echo "[deploy] health check passed"
    break
  fi

  if [[ "$attempt" -eq "$HEALTHCHECK_RETRIES" ]]; then
    echo "[deploy] health check failed after $HEALTHCHECK_RETRIES attempts" >&2
    exit 1
  fi

  echo "[deploy] service not ready yet, retrying in ${HEALTHCHECK_DELAY_SECONDS}s (attempt ${attempt}/${HEALTHCHECK_RETRIES})"
  sleep "$HEALTHCHECK_DELAY_SECONDS"
done

echo "[deploy] done"
