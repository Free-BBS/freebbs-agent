from __future__ import annotations

from .faiss_store import RetrievedChunk


def reciprocal_rank_fusion(
    ranked_lists: list[list[RetrievedChunk]],
    *,
    top_k: int,
    rank_constant: int = 60,
    weights: list[float] | None = None,
) -> list[RetrievedChunk]:
    if weights is not None and len(weights) != len(ranked_lists):
        raise ValueError("weights must match ranked_lists length")
    scores: dict[str, float] = {}
    chunks: dict[str, RetrievedChunk] = {}
    for list_index, hits in enumerate(ranked_lists):
        weight = weights[list_index] if weights is not None else 1.0
        for rank, hit in enumerate(hits, start=1):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + weight / (rank_constant + rank)
            chunks[hit.chunk_id] = hit
    ordered = sorted(scores, key=scores.get, reverse=True)[:top_k]
    return [
        RetrievedChunk(
            chunk_id=chunks[chunk_id].chunk_id,
            doc_id=chunks[chunk_id].doc_id,
            source=chunks[chunk_id].source,
            text=chunks[chunk_id].text,
            score=scores[chunk_id],
        )
        for chunk_id in ordered
    ]
