from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .keyword_search import BM25Retriever


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    doc_id: str
    source: str
    text: str
    score: float


class FaissVectorStore:
    def __init__(self, index, metadata: list[dict[str, Any]]):
        self._index = index
        self._metadata = metadata
        self._keyword_retriever = None

    @classmethod
    def build(cls, vectors: list[list[float]], metadata: list[dict[str, Any]]) -> "FaissVectorStore":
        if len(vectors) != len(metadata):
            raise ValueError("vectors and metadata must have same length")
        if not vectors:
            raise ValueError("vectors must not be empty")

        faiss = _require_faiss()
        np = _require_numpy()
        matrix = np.asarray(vectors, dtype="float32")
        if matrix.ndim != 2:
            raise ValueError("vectors must be a 2D array-like")
        faiss.normalize_L2(matrix)
        index = faiss.IndexFlatIP(matrix.shape[1])
        index.add(matrix)
        return cls(index=index, metadata=metadata)

    @classmethod
    def load(cls, index_path: str, metadata_path: str) -> "FaissVectorStore":
        faiss = _require_faiss()
        index_file = Path(index_path)
        metadata_file = Path(metadata_path)

        if not index_file.exists():
            raise FileNotFoundError(f"FAISS index file not found: {index_file}")
        if not metadata_file.exists():
            raise FileNotFoundError(f"FAISS metadata file not found: {metadata_file}")

        index = faiss.read_index(str(index_file))
        metadata = [
            json.loads(line)
            for line in metadata_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if index.ntotal != len(metadata):
            raise ValueError("FAISS index size does not match metadata rows")
        return cls(index=index, metadata=metadata)

    def save(self, index_path: str, metadata_path: str) -> None:
        faiss = _require_faiss()
        index_file = Path(index_path)
        metadata_file = Path(metadata_path)
        index_file.parent.mkdir(parents=True, exist_ok=True)
        metadata_file.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(index_file))
        metadata_file.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in self._metadata) + "\n",
            encoding="utf-8",
        )

    def search(self, query_vector: list[float], top_k: int) -> list[RetrievedChunk]:
        if top_k <= 0:
            return []
        np = _require_numpy()
        query = np.asarray([query_vector], dtype="float32")
        faiss = _require_faiss()
        faiss.normalize_L2(query)
        scores, indices = self._index.search(query, top_k)
        results: list[RetrievedChunk] = []
        for score, idx in zip(scores[0], indices[0], strict=False):
            if idx < 0 or idx >= len(self._metadata):
                continue
            row = self._metadata[idx]
            results.append(
                RetrievedChunk(
                    chunk_id=row.get("chunk_id", f"chunk_{idx}"),
                    doc_id=row.get("doc_id", ""),
                    source=row.get("source", ""),
                    text=row.get("text", ""),
                    score=float(score),
                )
            )
        return results

    def search_keywords(self, query: str, top_k: int) -> list[RetrievedChunk]:
        if self._keyword_retriever is None:
            self._keyword_retriever = BM25Retriever(self._metadata)
        results = []
        for idx, score in self._keyword_retriever.search(query, top_k=top_k):
            row = self._metadata[idx]
            results.append(
                RetrievedChunk(
                    chunk_id=row.get("chunk_id", f"chunk_{idx}"),
                    doc_id=row.get("doc_id", ""),
                    source=row.get("source", ""),
                    text=row.get("text", ""),
                    score=score,
                )
            )
        return results


def _require_faiss():
    try:
        import faiss
    except ImportError as exc:
        raise RuntimeError("faiss-cpu is required for RAG vector search") from exc
    return faiss


def _require_numpy():
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("numpy is required for RAG vector search") from exc
    return np
