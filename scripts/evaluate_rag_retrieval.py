#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from freebbs_agent.config import AgentConfig
from freebbs_agent.rag.embeddings import build_embedding_client
from freebbs_agent.rag.faiss_store import FaissVectorStore
from freebbs_agent.rag.fusion import reciprocal_rank_fusion


@dataclass(frozen=True)
class EvalCase:
    query: str
    expected_source_keywords: list[str]
    expected_text_keywords: list[str]
    note: str


DEFAULT_CASES = [
    EvalCase(
        query="ESP8266 的 AP 模式和 STA 模式有什么区别？",
        expected_source_keywords=["网络基础知识和8266实战"],
        expected_text_keywords=["ap", "sta", "esp8266"],
        note="当前语料里有网络和8266专题，应优先命中该资料。",
    ),
    EvalCase(
        query="HTTP 和 HTTPS 的差别是什么？",
        expected_source_keywords=["网络基础知识和8266实战"],
        expected_text_keywords=["http", "https"],
        note="检查基础网络概念能否回到网络讲义。",
    ),
    EvalCase(
        query="什么是 PCB，为什么要学 PCB 打板？",
        expected_source_keywords=["PCB设计打板基础和焊接技术进阶"],
        expected_text_keywords=["pcb", "打板"],
        note="应命中 PCB 教程开篇介绍。",
    ),
    EvalCase(
        query="DRC 检查在原理图阶段有什么作用？",
        expected_source_keywords=["PCB设计打板基础和焊接技术进阶"],
        expected_text_keywords=["drc", "检查"],
        note="应命中 PCB 讲义 DRC 部分。",
    ),
    EvalCase(
        query="Gerber 文件如何导出并下单？",
        expected_source_keywords=["PCB设计打板基础和焊接技术进阶"],
        expected_text_keywords=["gerber", "下单"],
        note="应命中 PCB 讲义导出和下单章节。",
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate retrieval quality against current RAG corpus.")
    parser.add_argument("--top-k", type=int, default=5, help="TopK results to inspect.")
    parser.add_argument(
        "--mode",
        choices=["vector", "hybrid"],
        default="hybrid",
        help="Evaluate vector-only retrieval or BM25+vector RRF fusion.",
    )
    parser.add_argument(
        "--query-set",
        default="",
        help="Optional JSON file path for custom query set. Schema: [{query, expected_source_keywords, expected_text_keywords, note}]",
    )
    return parser.parse_args()


def load_cases(query_set_path: str) -> list[EvalCase]:
    if not query_set_path:
        return DEFAULT_CASES
    path = Path(query_set_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases: list[EvalCase] = []
    for item in payload:
        cases.append(
            EvalCase(
                query=item["query"],
                expected_source_keywords=item.get("expected_source_keywords", []),
                expected_text_keywords=item.get("expected_text_keywords", []),
                note=item.get("note", ""),
            )
        )
    return cases


def is_relevant(source: str, text: str, case: EvalCase) -> bool:
    source_lower = source.lower()
    text_lower = text.lower()
    source_ok = any(key.lower() in source_lower for key in case.expected_source_keywords) if case.expected_source_keywords else True
    text_ok = any(key.lower() in text_lower for key in case.expected_text_keywords) if case.expected_text_keywords else True
    return source_ok or text_ok


def main() -> None:
    args = parse_args()
    config = AgentConfig.from_env()
    cases = load_cases(args.query_set)
    embedder = build_embedding_client(config)
    store = FaissVectorStore.load(config.rag_index_path, config.rag_metadata_path)

    hit_at_k = 0
    mrr_total = 0.0

    print("RAG retrieval evaluation (dataset-aligned):")
    print(f"- cases: {len(cases)}")
    print(f"- top_k: {args.top_k}")
    print(f"- mode: {args.mode}")
    print(f"- index: {config.rag_index_path}")
    print()

    for case_idx, case in enumerate(cases, start=1):
        query_vec = embedder.embed_query(case.query)
        vector_hits = store.search(query_vec, top_k=args.top_k)
        if args.mode == "hybrid":
            keyword_hits = store.search_keywords(case.query, top_k=args.top_k)
            hits = reciprocal_rank_fusion(
                [vector_hits, keyword_hits],
                top_k=args.top_k,
                weights=[1.0, 0.5],
            )
        else:
            hits = vector_hits

        first_relevant_rank = None
        for rank, hit in enumerate(hits, start=1):
            if is_relevant(hit.source, hit.text, case):
                first_relevant_rank = rank
                break

        if first_relevant_rank is not None:
            hit_at_k += 1
            mrr_total += 1.0 / first_relevant_rank

        print(f"[Case {case_idx}] {case.query}")
        print(f"  note: {case.note}")
        print(f"  first_relevant_rank: {first_relevant_rank if first_relevant_rank is not None else 'None'}")
        for rank, hit in enumerate(hits, start=1):
            snippet = hit.text.replace("\n", " ")[:90]
            relevant = "Y" if is_relevant(hit.source, hit.text, case) else "N"
            print(f"    {rank}. relevant={relevant} score={hit.score:.4f} source={hit.source} snippet={snippet}")
        print()

    total = len(cases)
    hit_k_rate = hit_at_k / total if total else 0.0
    mrr = mrr_total / total if total else 0.0
    print("Summary:")
    print(f"- Hit@{args.top_k}: {hit_at_k}/{total} = {hit_k_rate:.2%}")
    print(f"- MRR@{args.top_k}: {mrr:.4f}")


if __name__ == "__main__":
    main()
