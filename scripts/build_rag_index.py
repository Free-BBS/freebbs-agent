#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from freebbs_agent.config import AgentConfig
from freebbs_agent.rag.chunking import chunk_documents
from freebbs_agent.rag.embeddings import build_embedding_client
from freebbs_agent.rag.faiss_store import FaissVectorStore
from freebbs_agent.rag.ingest import clone_or_update_repo, load_documents_from_directory


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build FAISS index for FREE-BBS RAG data.")
    parser.add_argument(
        "--repo-url",
        default="",
        help="Optional single source repository URL. Overrides --sources-file.",
    )
    parser.add_argument(
        "--repo-dir",
        default="data/rag/source/2025HardWareContestOptionalPDFs_THUEE",
        help="Local checkout directory used with --repo-url.",
    )
    parser.add_argument(
        "--sources-file",
        default="data/rag/sources.json",
        help="JSON manifest containing repositories to index.",
    )
    parser.add_argument("--chunk-size", type=int, default=800, help="Chunk length in characters.")
    parser.add_argument("--chunk-overlap", type=int, default=120, help="Chunk overlap in characters.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = AgentConfig.from_env()

    sources = load_sources(args)
    documents = []
    for source in sources:
        if source.get("repo_url"):
            source_dir = clone_or_update_repo(source["repo_url"], source["repo_dir"])
        else:
            source_dir = Path(source["local_dir"])
        documents.extend(
            load_documents_from_directory(
                str(source_dir),
                source_prefix=source["id"],
            )
        )
    chunks = chunk_documents(documents, chunk_size=args.chunk_size, chunk_overlap=args.chunk_overlap)
    if not chunks:
        raise RuntimeError("No chunks produced from source documents")

    embedding_client = build_embedding_client(config)
    vectors = embedding_client.embed_documents([chunk.text for chunk in chunks])
    metadata = [
        {
            "chunk_id": chunk.chunk_id,
            "doc_id": chunk.doc_id,
            "source": chunk.source,
            "text": chunk.text,
        }
        for chunk in chunks
    ]

    store = FaissVectorStore.build(vectors, metadata)
    store.save(config.rag_index_path, config.rag_metadata_path)

    print("RAG index build finished:")
    print(f"- sources: {len(sources)}")
    print(f"- docs: {len(documents)}")
    print(f"- chunks: {len(chunks)}")
    print(f"- index: {Path(config.rag_index_path).resolve()}")
    print(f"- metadata: {Path(config.rag_metadata_path).resolve()}")
    print(f"- embedding provider: {config.rag_embedding_provider}")
    print(f"- embedding model: {config.rag_local_embedding_model if config.rag_embedding_provider == 'local' else config.rag_embedding_model}")


def load_sources(args: argparse.Namespace) -> list[dict[str, str]]:
    if args.repo_url:
        return [{"id": Path(args.repo_dir).name, "repo_url": args.repo_url, "repo_dir": args.repo_dir}]
    path = Path(args.sources_file)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("sources file must contain a non-empty JSON array")
    for source in payload:
        if not isinstance(source, dict) or "id" not in source:
            raise ValueError("each source must contain id")
        has_repo = bool(source.get("repo_url") and source.get("repo_dir"))
        has_local = bool(source.get("local_dir"))
        if has_repo == has_local:
            raise ValueError("each source must contain either repo_url/repo_dir or local_dir")
    return payload


if __name__ == "__main__":
    main()
