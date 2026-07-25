from __future__ import annotations

import sys
from pathlib import Path

from ..config import AgentConfig
from .paths import resolve_configured_rag_store_paths


def validate_rag_store_files(config) -> tuple[str, str]:
    index_path, metadata_path = resolve_configured_rag_store_paths(config)
    missing = [
        path
        for path in (index_path, metadata_path)
        if not Path(path).is_file()
    ]
    if missing:
        raise FileNotFoundError(
            "missing RAG index or metadata: " + ", ".join(missing)
        )
    return index_path, metadata_path


def main() -> int:
    try:
        index_path, metadata_path = validate_rag_store_files(AgentConfig.from_env())
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"RAG path preflight failed: {exc}", file=sys.stderr)
        return 1

    print(f"Using RAG index: {Path(index_path).resolve()}")
    print(f"Using RAG metadata: {Path(metadata_path).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
