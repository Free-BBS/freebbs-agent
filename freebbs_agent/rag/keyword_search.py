from __future__ import annotations

import math
import re
from collections import Counter


_LATIN_OR_NUMBER = re.compile(r"[a-zA-Z][a-zA-Z0-9_+.-]*|\d+(?:\.\d+)?")
_CJK_SEQUENCE = re.compile(r"[\u3400-\u9fff]+")


def tokenize(text: str) -> list[str]:
    value = text.lower()
    tokens = _LATIN_OR_NUMBER.findall(value)
    for sequence in _CJK_SEQUENCE.findall(value):
        tokens.extend(sequence)
        tokens.extend(sequence[index : index + 2] for index in range(len(sequence) - 1))
    return tokens


class BM25Retriever:
    def __init__(self, metadata: list[dict], *, k1: float = 1.5, b: float = 0.75):
        self._metadata = metadata
        self._k1 = k1
        self._b = b
        self._documents = [
            Counter(tokenize(f'{row.get("source", "")} {row.get("text", "")}'))
            for row in metadata
        ]
        self._lengths = [sum(document.values()) for document in self._documents]
        self._average_length = sum(self._lengths) / len(self._lengths) if self._lengths else 0.0
        self._document_frequency: Counter[str] = Counter()
        for document in self._documents:
            self._document_frequency.update(document.keys())

    def search(self, query: str, *, top_k: int) -> list[tuple[int, float]]:
        if top_k <= 0 or not self._documents:
            return []
        query_terms = set(tokenize(query))
        scores: list[tuple[int, float]] = []
        total_documents = len(self._documents)
        for index, document in enumerate(self._documents):
            score = 0.0
            length = self._lengths[index]
            for term in query_terms:
                frequency = document.get(term, 0)
                if not frequency:
                    continue
                document_frequency = self._document_frequency[term]
                inverse_document_frequency = math.log(
                    1 + (total_documents - document_frequency + 0.5) / (document_frequency + 0.5)
                )
                normalization = frequency + self._k1 * (
                    1 - self._b + self._b * length / (self._average_length or 1.0)
                )
                score += inverse_document_frequency * frequency * (self._k1 + 1) / normalization
            if score > 0:
                scores.append((index, score))
        return sorted(scores, key=lambda item: item[1], reverse=True)[:top_k]
