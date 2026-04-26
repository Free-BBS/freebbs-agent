#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[ci] installing dependencies"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

echo "[ci] syntax check"
.venv/bin/python -m compileall app.py freebbs_agent tests

echo "[ci] running tests"
.venv/bin/python -m unittest discover -s tests

echo "[ci] validating required files"
test -f app.py
test -f requirements.txt
test -f .env.example
test -f deploy/systemd/free-bbs-agent.service

echo "[ci] done"
