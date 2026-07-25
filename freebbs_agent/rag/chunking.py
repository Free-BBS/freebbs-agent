from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceDocument:
    doc_id: str
    source: str
    text: str


@dataclass(frozen=True)
class ChunkRecord:
    chunk_id: str
    doc_id: str
    source: str
    text: str


def chunk_documents(
    documents: list[SourceDocument],
    *,
    chunk_size: int = 800,
    chunk_overlap: int = 120,
) -> list[ChunkRecord]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be >=0 and < chunk_size")

    records: list[ChunkRecord] = []
    step = chunk_size - chunk_overlap

    for doc in documents:
        text = _normalize_text(doc.text)
        if not text:
            continue

        if len(text) <= chunk_size:
            records.append(
                ChunkRecord(
                    chunk_id=f"{doc.doc_id}#0",
                    doc_id=doc.doc_id,
                    source=doc.source,
                    text=text,
                )
            )
            continue

        index = 0
        chunk_num = 0
        while index < len(text):
            part = text[index : index + chunk_size].strip()
            if part:
                records.append(
                    ChunkRecord(
                        chunk_id=f"{doc.doc_id}#{chunk_num}",
                        doc_id=doc.doc_id,
                        source=doc.source,
                        text=part,
                    )
                )
                chunk_num += 1
            index += step

    return records


def _normalize_text(value: str) -> str:
    return "\n".join(line.strip() for line in value.splitlines() if line.strip()).strip()
