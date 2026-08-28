#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[ci] installing dependencies"
python3 -m venv .venv
.venv/bin/python -m pip install --retries 5 --timeout 60 -r requirements.txt

echo "[ci] syntax check"
.venv/bin/python -m compileall app.py freebbs_agent scripts tests
for script in scripts/*.sh; do
  bash -n "$script"
done

echo "[ci] running tests"
.venv/bin/python -m unittest discover -s tests

echo "[ci] validating required files"
test -f app.py
test -f requirements.txt
test -f .env.example
test -f deploy/systemd/free-bbs-agent.service
test -f deploy/systemd/free-bbs-rag-indexer.service
test -f deploy/systemd/free-bbs-rag-indexer.timer

echo "[ci] done"
