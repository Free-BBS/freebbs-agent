from __future__ import annotations

import re
from dataclasses import dataclass

from .chunking import SourceDocument


@dataclass(frozen=True)
class SmartChunkRecord:
    chunk_id: str
    doc_id: str
    source: str
    text: str
    chunk_index: int
    start_char: int
    end_char: int
    heading: str | None = None


@dataclass(frozen=True)
class TextBlock:
    text: str
    start_char: int
    end_char: int
    heading: str | None = None


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[。！？!?；;：:\.])\s+")


def smart_chunk_documents(
    documents: list[SourceDocument],
    *,
    chunk_size: int = 800,
    chunk_overlap: int = 120,
    min_chunk_size: int = 120,
) -> list[SmartChunkRecord]:
    """Chunk documents with structure-aware boundaries.

    The existing chunker slices by raw character windows. This version keeps
    Markdown sections and paragraphs together where possible, then falls back
    to sentence or character windows only for oversized blocks.
    """

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be >=0 and < chunk_size")
    if min_chunk_size < 0:
        raise ValueError("min_chunk_size must be >=0")
    if min_chunk_size >= chunk_size:
        raise ValueError("min_chunk_size must be smaller than chunk_size")

    records: list[SmartChunkRecord] = []
    for doc in documents:
        text = _normalize_text(doc.text)
        if not text:
            continue

        blocks = _split_into_blocks(text)
        chunks = _pack_blocks(blocks, chunk_size=chunk_size, min_chunk_size=min_chunk_size)

        chunk_index = 0
        for chunk in chunks:
            for part in _split_oversized_block(chunk, chunk_size=chunk_size, chunk_overlap=chunk_overlap):
                if not part.text:
                    continue
                records.append(
                    SmartChunkRecord(
                        chunk_id=f"{doc.doc_id}#{chunk_index}",
                        doc_id=doc.doc_id,
                        source=doc.source,
                        text=part.text,
                        chunk_index=chunk_index,
                        start_char=part.start_char,
                        end_char=part.end_char,
                        heading=part.heading,
                    )
                )
                chunk_index += 1

    return records


def _normalize_text(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n")]

    compacted: list[str] = []
    blank_seen = False
    for line in lines:
        if line.strip():
            compacted.append(line)
            blank_seen = False
        elif not blank_seen:
            compacted.append("")
            blank_seen = True

    return "\n".join(compacted).strip()


def _split_into_blocks(text: str) -> list[TextBlock]:
    blocks: list[TextBlock] = []
    current_heading: str | None = None
    position = 0

    for raw_block in re.split(r"\n{2,}", text):
        block = raw_block.strip()
        if not block:
            position += len(raw_block) + 2
            continue

        start = text.find(block, position)
        if start < 0:
            start = position
        end = start + len(block)
        position = end

        heading_match = HEADING_RE.match(block.splitlines()[0])
        if heading_match:
            current_heading = heading_match.group(2).strip()

        blocks.append(
            TextBlock(
                text=block,
                start_char=start,
                end_char=end,
                heading=current_heading,
            )
        )

    return blocks


def _pack_blocks(
    blocks: list[TextBlock],
    *,
    chunk_size: int,
    min_chunk_size: int,
) -> list[TextBlock]:
    chunks: list[TextBlock] = []
    current_parts: list[TextBlock] = []
    current_len = 0

    for block in blocks:
        separator_len = 2 if current_parts else 0
        would_len = current_len + separator_len + len(block.text)

        if current_parts and would_len > chunk_size and current_len >= min_chunk_size:
            chunks.append(_merge_blocks(current_parts))
            current_parts = [block]
            current_len = len(block.text)
            continue

        current_parts.append(block)
        current_len = would_len

    if current_parts:
        chunks.append(_merge_blocks(current_parts))

    return chunks


def _merge_blocks(blocks: list[TextBlock]) -> TextBlock:
    return TextBlock(
        text="\n\n".join(block.text for block in blocks).strip(),
        start_char=blocks[0].start_char,
        end_char=blocks[-1].end_char,
        heading=blocks[0].heading,
    )


def _split_oversized_block(
    block: TextBlock,
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> list[TextBlock]:
    if len(block.text) <= chunk_size:
        return [block]

    sentences = _split_sentences(block.text)
    if len(sentences) > 1:
        sentence_blocks = _pack_sentence_parts(
            block,
            sentences,
            chunk_size=chunk_size,
        )
        if all(len(part.text) <= chunk_size for part in sentence_blocks):
            return sentence_blocks

    return _sliding_window_split(block, chunk_size=chunk_size, chunk_overlap=chunk_overlap)


def _split_sentences(text: str) -> list[str]:
    parts = SENTENCE_BOUNDARY_RE.split(text)
    return [part.strip() for part in parts if part.strip()]


def _pack_sentence_parts(
    block: TextBlock,
    sentences: list[str],
    *,
    chunk_size: int,
) -> list[TextBlock]:
    chunks: list[TextBlock] = []
    current: list[str] = []
    current_len = 0
    search_from = 0
    chunk_start = block.start_char

    for sentence in sentences:
        separator_len = 1 if current else 0
        would_len = current_len + separator_len + len(sentence)
        if current and would_len > chunk_size:
            text = " ".join(current).strip()
            chunks.append(
                TextBlock(
                    text=text,
                    start_char=chunk_start,
                    end_char=chunk_start + len(text),
                    heading=block.heading,
                )
            )
            current = []
            current_len = 0

        if not current:
            relative_start = block.text.find(sentence, search_from)
            if relative_start >= 0:
                chunk_start = block.start_char + relative_start
                search_from = relative_start + len(sentence)

        current.append(sentence)
        current_len = len(" ".join(current))

    if current:
        text = " ".join(current).strip()
        chunks.append(
            TextBlock(
                text=text,
                start_char=chunk_start,
                end_char=chunk_start + len(text),
                heading=block.heading,
            )
        )

    return chunks


def _sliding_window_split(
    block: TextBlock,
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> list[TextBlock]:
    parts: list[TextBlock] = []
    step = chunk_size - chunk_overlap
    index = 0

    while index < len(block.text):
        raw_part = block.text[index : index + chunk_size]
        stripped = raw_part.strip()
        if stripped:
            leading_spaces = len(raw_part) - len(raw_part.lstrip())
            start = block.start_char + index + leading_spaces
            parts.append(
                TextBlock(
                    text=stripped,
                    start_char=start,
                    end_char=start + len(stripped),
                    heading=block.heading,
                )
            )
        index += step

    return parts
