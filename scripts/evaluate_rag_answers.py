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

from freebbs_agent.agent_utils import AgentInvocation, ChatOptions
from freebbs_agent.agents import GeneralChatAgent
from freebbs_agent.ai_client import ChatClient
from freebbs_agent.config import AgentConfig
from freebbs_agent.rag_agent import RagAgent


JUDGE_PROMPT = """你是 RAG 回答质量评测员。比较两个候选回答，不猜测它们来自哪个系统。
根据问题、参考事实和候选回答，分别对以下维度打 0-5 分：
correctness（事实正确）、completeness（覆盖参考事实）、groundedness（不编造资料内容）、
relevance（直接回答问题）、traceability（引用或来源可追溯）。
同时给出 winner，只能是 A、B 或 tie。只输出严格 JSON：
{"A":{"correctness":0,"completeness":0,"groundedness":0,"relevance":0,"traceability":0},
"B":{"correctness":0,"completeness":0,"groundedness":0,"relevance":0,"traceability":0},
"winner":"A|B|tie","reason":"简短理由"}"""


@dataclass(frozen=True)
class EvalCase:
    id: str
    question: str
    reference_facts: list[str]
    expected_source_keywords: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare answer quality with and without RAG.")
    parser.add_argument(
        "--query-set",
        default="data/rag/evals/rag_answer_quality_queries.json",
    )
    parser.add_argument(
        "--output",
        default="data/rag/evals/results/rag_answer_quality.json",
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--skip-judge", action="store_true")
    return parser.parse_args()


def load_cases(path: str) -> list[EvalCase]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        EvalCase(
            id=item["id"],
            question=item["question"],
            reference_facts=item.get("reference_facts", []),
            expected_source_keywords=item.get("expected_source_keywords", []),
        )
        for item in payload
    ]


def invocation(question: str, agent: str, system_prompt: str) -> AgentInvocation:
    return AgentInvocation(
        payload={"agent": agent, "message": question},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ],
        options=ChatOptions(temperature=0),
    )


def judge_pair(client: ChatClient, config: AgentConfig, case: EvalCase, first: dict, second: dict) -> dict:
    payload = {
        "question": case.question,
        "reference_facts": case.reference_facts,
        "A": {"answer": first["answer"], "sources": first.get("sources", [])},
        "B": {"answer": second["answer"], "sources": second.get("sources", [])},
    }
    result = client.chat(
        [
            {"role": "system", "content": JUDGE_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        temperature=0,
        max_tokens=500,
    )
    return parse_json_object(result["answer"])


def parse_json_object(value: str) -> dict:
    text = (value or "").strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("judge response must be a JSON object")
    return payload


def fact_coverage(answer: str, reference_facts: list[str]) -> dict:
    normalized = answer.lower().replace(" ", "")
    hits = [fact for fact in reference_facts if fact.lower().replace(" ", "") in normalized]
    return {
        "exact_fact_hits": len(hits),
        "reference_fact_count": len(reference_facts),
        "exact_fact_coverage": len(hits) / len(reference_facts) if reference_facts else 0.0,
        "matched_facts": hits,
    }


def main() -> None:
    args = parse_args()
    config = AgentConfig.from_env()
    if not config.api_key:
        raise RuntimeError("AGENT_API_KEY or OPENAI_API_KEY is required for answer evaluation")
    if not config.rag_enabled:
        raise RuntimeError("RAG_ENABLED=true is required for answer evaluation")

    cases = load_cases(args.query_set)
    if args.limit > 0:
        cases = cases[: args.limit]
    client = ChatClient(config)
    general_agent = GeneralChatAgent(config, client)
    rag_agent = RagAgent(config, client)
    rows = []

    for index, case in enumerate(cases):
        no_rag = general_agent.run(invocation(case.question, "general_chat", config.system_prompt))
        with_rag = rag_agent.run(invocation(case.question, "rag", config.system_prompt))
        row = {
            "id": case.id,
            "question": case.question,
            "reference_facts": case.reference_facts,
            "no_rag": {
                **no_rag,
                "fact_coverage": fact_coverage(no_rag["answer"], case.reference_facts),
            },
            "with_rag": {
                **with_rag,
                "fact_coverage": fact_coverage(with_rag["answer"], case.reference_facts),
            },
        }
        if not args.skip_judge:
            # Alternate order to reduce systematic position bias.
            rag_is_a = index % 2 == 1
            first, second = (with_rag, no_rag) if rag_is_a else (no_rag, with_rag)
            judgment = judge_pair(client, config, case, first, second)
            row["judge"] = {
                "blind_order": {"A": "with_rag" if rag_is_a else "no_rag", "B": "no_rag" if rag_is_a else "with_rag"},
                "result": judgment,
            }
        rows.append(row)
        print(f"[{index + 1}/{len(cases)}] {case.id} complete")

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Results written to {output}")


if __name__ == "__main__":
    main()
