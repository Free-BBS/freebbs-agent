from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RagIndexManifest:
    version: str
    revision: str
    index_path: str
    metadata_path: str
    document_count: int = 0
    chunk_count: int = 0
    built_at: str = ""


def load_rag_index_manifest(path: str) -> RagIndexManifest:
    manifest_path = Path(path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("RAG index manifest must be an object")

    version = _required_string(payload, "version")
    revision = _required_string(payload, "revision")
    index_path = _resolve_manifest_member(manifest_path, payload, "index_path")
    metadata_path = _resolve_manifest_member(manifest_path, payload, "metadata_path")
    return RagIndexManifest(
        version=version,
        revision=revision,
        index_path=index_path,
        metadata_path=metadata_path,
        document_count=_non_negative_int(payload.get("document_count", 0)),
        chunk_count=_non_negative_int(payload.get("chunk_count", 0)),
        built_at=str(payload.get("built_at") or ""),
    )


def write_rag_index_manifest(path: str, payload: dict[str, Any]) -> None:
    manifest_path = Path(path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = manifest_path.with_name(f".{manifest_path.name}.{os.getpid()}.tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary_path, manifest_path)


def active_store_paths(
    manifest_path: str,
    fallback_paths: tuple[str, str],
) -> tuple[tuple[str, str], str]:
    if not Path(manifest_path).is_file():
        return fallback_paths, "static"
    manifest = load_rag_index_manifest(manifest_path)
    return (manifest.index_path, manifest.metadata_path), manifest.version


def _resolve_manifest_member(
    manifest_path: Path,
    payload: dict[str, Any],
    key: str,
) -> str:
    raw_path = _required_string(payload, key)
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = manifest_path.parent / candidate
    return str(candidate.resolve())


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        normalized = str(value).strip()
        if normalized:
            return normalized
    raise ValueError(f"RAG index manifest {key} is required")


def _non_negative_int(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("RAG index manifest count must be an integer")
    parsed = int(value)
    if parsed < 0:
        raise ValueError("RAG index manifest count must not be negative")
    return parsed
