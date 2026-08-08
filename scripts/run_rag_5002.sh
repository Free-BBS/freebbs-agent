#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

PORT="${PORT:-5002}"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"
DEFAULT_MODEL_DIR="$PROJECT_ROOT/data/models/bge-small-zh-v1.5"
DEFAULT_INDEX_PATH="data/rag/index.faiss"
DEFAULT_METADATA_PATH="data/rag/metadata.jsonl"

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "Missing virtualenv python: $VENV_PYTHON"
  echo "Run: python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

if [[ ! -f "$PROJECT_ROOT/$DEFAULT_INDEX_PATH" || ! -f "$PROJECT_ROOT/$DEFAULT_METADATA_PATH" ]]; then
  echo "Missing RAG index or metadata."
  echo "Run: $VENV_PYTHON scripts/build_rag_index.py"
  exit 1
fi

if [[ ! -d "$DEFAULT_MODEL_DIR" ]]; then
  echo "Missing local embedding model directory: $DEFAULT_MODEL_DIR"
  echo "Run: $VENV_PYTHON scripts/prepare_local_embedding_model.py --source auto"
  exit 1
fi

if ss -ltn | awk -v port="127.0.0.1:${PORT}" '$4 == port {found=1} END {exit !found}'; then
  echo "Port ${PORT} is already in use."
  echo "Set a different port via: PORT=5003 scripts/run_rag_5002.sh"
  exit 1
fi

echo "Starting RAG-enabled app on http://127.0.0.1:${PORT}"
echo "Test page: http://127.0.0.1:${PORT}/dev/agent-test"

AGENT_PORT="${PORT}" \
RAG_ENABLED=true \
RAG_INDEX_PATH="${RAG_INDEX_PATH:-$DEFAULT_INDEX_PATH}" \
RAG_METADATA_PATH="${RAG_METADATA_PATH:-$DEFAULT_METADATA_PATH}" \
RAG_EMBEDDING_PROVIDER="${RAG_EMBEDDING_PROVIDER:-local}" \
RAG_LOCAL_MODEL_DIR="${RAG_LOCAL_MODEL_DIR:-$DEFAULT_MODEL_DIR}" \
RAG_LOCAL_FILES_ONLY="${RAG_LOCAL_FILES_ONLY:-true}" \
RAG_HF_ENDPOINT="${RAG_HF_ENDPOINT:-https://hf-mirror.com}" \
"$VENV_PYTHON" app.py
