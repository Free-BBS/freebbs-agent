#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from freebbs_agent.config import AgentConfig
from freebbs_agent.rag.course_snapshot import (
    course_snapshot_documents,
    fetch_course_snapshot,
)
from freebbs_agent.rag.embeddings import build_embedding_client
from freebbs_agent.rag.faiss_store import FaissVectorStore
from freebbs_agent.rag.manifest import (
    load_rag_index_manifest,
    write_rag_index_manifest,
)
from freebbs_agent.rag.paths import (
    resolve_configured_rag_manifest_path,
    resolve_configured_rag_store_paths,
)
from freebbs_agent.rag.smart_chunking import smart_chunk_documents


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Synchronize Web course data into a versioned FREE-BBS RAG index."
    )
    parser.add_argument("--force", action="store_true", help="Build even if revision is unchanged.")
    parser.add_argument(
        "--without-seed",
        action="store_true",
        help="Do not preserve non-course chunks from the configured static metadata file.",
    )
    parser.add_argument("--chunk-size", type=int, default=800)
    parser.add_argument("--chunk-overlap", type=int, default=120)
    return parser.parse_args()


def load_seed_metadata(metadata_path: str) -> list[dict]:
    path = Path(metadata_path)
    if not path.is_file():
        return []
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or not isinstance(row.get("text"), str):
            raise ValueError(f"invalid seed metadata row at line {line_number}")
        if row.get("source_type") == "course_map":
            continue
        rows.append({**row, "source_type": row.get("source_type") or "seed"})
    return rows


def current_revision(manifest_path: str) -> str | None:
    try:
        return load_rag_index_manifest(manifest_path).revision
    except FileNotFoundError:
        return None


def safe_version_name(revision: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", revision).strip("-.") or "unknown"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"revision-{normalized}-{timestamp}"


def prune_versions(versions_dir: Path, *, keep: int, active_dir: Path) -> None:
    candidates = sorted(
        (
            path
            for path in versions_dir.iterdir()
            if path.is_dir() and path.name.startswith("revision-") and path.resolve() != active_dir.resolve()
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for stale_dir in candidates[max(0, keep - 1) :]:
        shutil.rmtree(stale_dir)


def main() -> int:
    args = parse_args()
    config = AgentConfig.from_env()
    snapshot = fetch_course_snapshot(config)
    manifest_path = resolve_configured_rag_manifest_path(config)
    revision = snapshot["revision"]

    if not args.force and current_revision(manifest_path) == revision:
        print(f"RAG course index is already current at revision {revision}")
        return 0

    documents, document_metadata = course_snapshot_documents(
        snapshot,
        web_base_url=config.web_base_url,
    )
    chunks = smart_chunk_documents(
        documents,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
    )
    course_rows = []
    for chunk in chunks:
        chunk_metadata = document_metadata[chunk.doc_id]
        retrieval_prefix = (
            f"课程：{chunk_metadata['course_name']}\n"
            f"知识点编号：{chunk_metadata['node_id']}\n"
            f"知识点：{chunk_metadata['title']}"
        )
        chunk_text = chunk.text
        if not chunk_text.startswith(f"课程：{chunk_metadata['course_name']}"):
            chunk_text = f"{retrieval_prefix}\n\n{chunk_text}"
        course_rows.append(
            {
                **chunk_metadata,
                "chunk_id": chunk.chunk_id,
                "doc_id": chunk.doc_id,
                "source": chunk.source,
                "text": chunk_text,
                "heading": chunk.heading or "",
                "chunk_index": chunk.chunk_index,
            }
        )

    seed_rows = []
    if not args.without_seed:
        _, seed_metadata_path = resolve_configured_rag_store_paths(config)
        if not Path(seed_metadata_path).is_file() and not Path(
            config.rag_metadata_path
        ).is_absolute():
            repository_seed_path = PROJECT_ROOT / config.rag_metadata_path
            if repository_seed_path.is_file():
                seed_metadata_path = str(repository_seed_path)
        seed_rows = load_seed_metadata(seed_metadata_path)
    metadata = seed_rows + course_rows
    if not metadata:
        raise RuntimeError("course snapshot and seed index produced no RAG chunks")

    embedding_client = build_embedding_client(config)
    vectors = embedding_client.embed_documents([row["text"] for row in metadata])
    store = FaissVectorStore.build(vectors, metadata)

    manifest_file = Path(manifest_path).resolve()
    versions_dir = manifest_file.parent / "versions"
    version = safe_version_name(revision)
    version_dir = versions_dir / version
    version_dir.mkdir(parents=True, exist_ok=False)
    index_path = version_dir / "index.faiss"
    metadata_path = version_dir / "metadata.jsonl"
    store.save(str(index_path), str(metadata_path))
    FaissVectorStore.load(str(index_path), str(metadata_path))

    built_at = datetime.now(timezone.utc).isoformat()
    write_rag_index_manifest(
        str(manifest_file),
        {
            "version": version,
            "revision": revision,
            "index_path": str(index_path.resolve()),
            "metadata_path": str(metadata_path.resolve()),
            "document_count": len({row.get("doc_id") for row in metadata}),
            "chunk_count": len(metadata),
            "course_document_count": len(documents),
            "course_chunk_count": len(course_rows),
            "seed_chunk_count": len(seed_rows),
            "built_at": built_at,
        },
    )
    prune_versions(
        versions_dir,
        keep=config.rag_version_retention,
        active_dir=version_dir,
    )

    print("RAG course index synchronized:")
    print(f"- snapshot revision: {revision}")
    print(f"- course nodes: {len(snapshot['documents'])}")
    print(f"- course chunks: {len(course_rows)}")
    print(f"- preserved seed chunks: {len(seed_rows)}")
    print(f"- version: {version}")
    print(f"- manifest: {manifest_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
