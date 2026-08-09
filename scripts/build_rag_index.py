#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
from freebbs_agent.rag.paths import (
    course_materials_root_for_config,
    resolve_rag_store_paths,
    resolve_under_course_root,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build FAISS index for FREE-BBS RAG data.")
    parser.add_argument(
        "--repo-url",
        default="https://github.com/Lucas-Song-zero/2025HardWareContestOptionalPDFs_THUEE.git",
        help="Source repository URL for first-stage materials.",
    )
    parser.add_argument(
        "--repo-dir",
        default="data/rag/source/2025HardWareContestOptionalPDFs_THUEE",
        help="Local checkout directory for source repository.",
    )
    parser.add_argument("--chunk-size", type=int, default=800, help="Chunk length in characters.")
    parser.add_argument("--chunk-overlap", type=int, default=120, help="Chunk overlap in characters.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = AgentConfig.from_env()
    course_materials_root = course_materials_root_for_config(config)

    repo_dir = resolve_under_course_root(args.repo_dir, course_materials_root)
    index_path, metadata_path = resolve_rag_store_paths(
        config.rag_index_path,
        config.rag_metadata_path,
        course_materials_root,
    )
    source_dir = clone_or_update_repo(args.repo_url, repo_dir)
    documents = load_documents_from_directory(str(source_dir))
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
    store.save(index_path, metadata_path)

    print("RAG index build finished:")
    print(f"- source repo: {args.repo_url}")
    print(f"- local source: {Path(source_dir).resolve()}")
    print(f"- docs: {len(documents)}")
    print(f"- chunks: {len(chunks)}")
    print(f"- index: {Path(index_path).resolve()}")
    print(f"- metadata: {Path(metadata_path).resolve()}")
    print(f"- embedding provider: {config.rag_embedding_provider}")
    print(f"- embedding model: {config.rag_local_embedding_model if config.rag_embedding_provider == 'local' else config.rag_embedding_model}")


if __name__ == "__main__":
    main()
